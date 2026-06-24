from __future__ import annotations

from collections import defaultdict
from enum import Enum

from pydantic import BaseModel, Field

from crisis_room.engine.actions import ActionDefinition, ActionPackage
from crisis_room.engine.resources import merge_requirements
from crisis_room.state.backchannels import BackchannelThreadStatus
from crisis_room.state.signals import SignalChannel
from crisis_room.state.world import WorldStateV2


class BatchWarningSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"


class BatchValidationWarning(BaseModel):
    code: str
    message: str
    severity: BatchWarningSeverity = BatchWarningSeverity.WARNING
    actor_id: str | None = None
    action_ids: list[str] = Field(default_factory=list)
    package_ids: list[str] = Field(default_factory=list)
    resource: str | None = None
    target_ids: list[str] = Field(default_factory=list)
    player_visible: bool = True


class BatchValidationReport(BaseModel):
    warnings: list[BatchValidationWarning] = Field(default_factory=list)

    @property
    def has_warnings(self) -> bool:
        return bool(self.warnings)


def build_batch_validation_report(
    world_state: WorldStateV2,
    action_packages: list[ActionPackage],
    action_catalog: list[ActionDefinition],
    *,
    player_entity_id: str,
) -> BatchValidationReport:
    catalog = {definition.action_id: definition for definition in action_catalog}
    warnings: list[BatchValidationWarning] = []
    warnings.extend(_duplicate_cooldown_warnings(action_packages, catalog))
    warnings.extend(_resource_contention_warnings(world_state, action_packages, catalog))
    warnings.extend(_public_covert_pairing_warnings(action_packages, catalog))
    warnings.extend(
        _backchannel_channel_warnings(
            world_state,
            action_packages,
            catalog,
            player_entity_id=player_entity_id,
        )
    )
    warnings.extend(_fallback_misuse_warnings(action_packages, catalog))
    return BatchValidationReport(
        warnings=_apply_player_visibility(
            _dedupe_warnings(warnings),
            player_entity_id=player_entity_id,
        )
    )


def format_batch_warning(warning: BatchValidationWarning) -> str:
    return warning.message


def _duplicate_cooldown_warnings(
    action_packages: list[ActionPackage],
    catalog: dict[str, ActionDefinition],
) -> list[BatchValidationWarning]:
    by_actor_action: dict[tuple[str, str], list[ActionPackage]] = defaultdict(list)
    for package in action_packages:
        definition = catalog.get(package.action_id)
        if definition is None or definition.cooldown_turns <= 0:
            continue
        by_actor_action[(package.actor_id, package.action_id)].append(package)

    warnings: list[BatchValidationWarning] = []
    for (actor_id, action_id), packages in by_actor_action.items():
        if len(packages) < 2:
            continue
        definition = catalog[action_id]
        warnings.append(
            BatchValidationWarning(
                code="duplicate_cooldown_action",
                actor_id=actor_id,
                action_ids=[action_id],
                package_ids=[package.package_id for package in packages],
                message=(
                    f"{actor_id} submitted {definition.title} more than once; "
                    "the first accepted package can place the rest on cooldown."
                ),
            )
        )
    return warnings


def _resource_contention_warnings(
    world_state: WorldStateV2,
    action_packages: list[ActionPackage],
    catalog: dict[str, ActionDefinition],
) -> list[BatchValidationWarning]:
    by_actor_resource: dict[tuple[str, str], list[ActionPackage]] = defaultdict(list)
    totals: dict[tuple[str, str], int] = defaultdict(int)
    for package in action_packages:
        definition = catalog.get(package.action_id)
        actor = world_state.actors.get(package.actor_id)
        if definition is None or actor is None:
            continue
        spend = _resource_spend(definition)
        for resource, amount in spend.items():
            if amount <= 0:
                continue
            key = (package.actor_id, resource)
            by_actor_resource[key].append(package)
            totals[key] += amount

    warnings: list[BatchValidationWarning] = []
    for (actor_id, resource), packages in by_actor_resource.items():
        if len(packages) < 2:
            continue
        available = world_state.actors[actor_id].resources.get(resource, 0)
        total = totals[(actor_id, resource)]
        if total <= available:
            continue
        action_titles = [
            catalog[package.action_id].title
            for package in packages
            if package.action_id in catalog
        ]
        warnings.append(
            BatchValidationWarning(
                code="resource_contention",
                actor_id=actor_id,
                action_ids=[package.action_id for package in packages],
                package_ids=[package.package_id for package in packages],
                resource=resource,
                message=(
                    f"{actor_id} queued actions that may overspend {resource}: "
                    f"{total} requested, {available} available "
                    f"({', '.join(action_titles)})."
                ),
            )
        )
    return warnings


def _public_covert_pairing_warnings(
    action_packages: list[ActionPackage],
    catalog: dict[str, ActionDefinition],
) -> list[BatchValidationWarning]:
    by_actor_target: dict[tuple[str, str], list[ActionPackage]] = defaultdict(list)
    for package in action_packages:
        for target_id in package.target_ids:
            by_actor_target[(package.actor_id, target_id)].append(package)

    warnings: list[BatchValidationWarning] = []
    covert_channels = {SignalChannel.BACKCHANNEL, SignalChannel.PRIVATE_DIPLOMATIC}
    for (actor_id, target_id), packages in by_actor_target.items():
        public_packages = [
            package for package in packages if package.channel == SignalChannel.PUBLIC
        ]
        covert_packages = [
            package for package in packages if package.channel in covert_channels
        ]
        if not public_packages or not covert_packages:
            continue
        public_escalatory = any(
            _definition_risk(catalog, package) >= 0.3 for package in public_packages
        )
        covert_deescalatory = any(
            _definition_deescalation(catalog, package) >= 0.25 for package in covert_packages
        )
        if not public_escalatory or not covert_deescalatory:
            continue
        packages_to_report = [*public_packages, *covert_packages]
        warnings.append(
            BatchValidationWarning(
                code="public_covert_tension",
                actor_id=actor_id,
                action_ids=[package.action_id for package in packages_to_report],
                package_ids=[package.package_id for package in packages_to_report],
                target_ids=[target_id],
                message=(
                    f"{actor_id} is combining public pressure with private off-ramp "
                    f"signals toward {target_id}; keep the public line from "
                    "undercutting the private channel."
                ),
            )
        )
    return warnings


def _backchannel_channel_warnings(
    world_state: WorldStateV2,
    action_packages: list[ActionPackage],
    catalog: dict[str, ActionDefinition],
    *,
    player_entity_id: str,
) -> list[BatchValidationWarning]:
    warnings: list[BatchValidationWarning] = []
    for package in action_packages:
        if package.channel != SignalChannel.BACKCHANNEL:
            continue
        if package.actor_id != player_entity_id:
            continue
        for target_id in package.target_ids:
            if _has_open_backchannel(world_state, package.actor_id, target_id):
                continue
            definition = catalog.get(package.action_id)
            if definition is not None and "backchannel" in definition.action_id:
                continue
            warnings.append(
                BatchValidationWarning(
                    code="missing_backchannel_thread",
                    actor_id=package.actor_id,
                    action_ids=[package.action_id],
                    package_ids=[package.package_id],
                    target_ids=[target_id],
                    message=(
                        f"{package.actor_id} is using a backchannel to {target_id} "
                        "without an existing thread; the action may need to open "
                        "or refresh the channel first."
                    ),
                )
            )
    return warnings


def _fallback_misuse_warnings(
    action_packages: list[ActionPackage],
    catalog: dict[str, ActionDefinition],
) -> list[BatchValidationWarning]:
    warnings: list[BatchValidationWarning] = []
    for package in action_packages:
        if not package.fallback_condition:
            continue
        if package.requested_timing not in {"current_turn", "now", "immediate"}:
            continue
        definition = catalog.get(package.action_id)
        title = definition.title if definition is not None else package.action_id
        warnings.append(
            BatchValidationWarning(
                code="fallback_submitted_now",
                actor_id=package.actor_id,
                action_ids=[package.action_id],
                package_ids=[package.package_id],
                message=(
                    f"{title} includes a fallback condition but is submitted for "
                    "current-turn execution; consider making it a clear primary "
                    "action or holding it for later."
                ),
            )
        )
    return warnings


def _resource_spend(definition: ActionDefinition) -> dict[str, int]:
    spend = dict(definition.resource_costs)
    effect_spend = {
        resource: abs(delta)
        for resource, delta in definition.actor_resource_effects.items()
        if delta < 0
    }
    return merge_requirements(spend, effect_spend)


def _definition_risk(
    catalog: dict[str, ActionDefinition],
    package: ActionPackage,
) -> float:
    definition = catalog.get(package.action_id)
    return definition.escalation_risk if definition is not None else 0.0


def _definition_deescalation(
    catalog: dict[str, ActionDefinition],
    package: ActionPackage,
) -> float:
    definition = catalog.get(package.action_id)
    return definition.deescalation_potential if definition is not None else 0.0


def _has_open_backchannel(
    world_state: WorldStateV2,
    actor_id: str,
    target_id: str,
) -> bool:
    first, second = sorted([actor_id, target_id])
    thread = world_state.backchannel_threads.get(f"backchannel:{first}:{second}")
    return thread is not None and thread.status == BackchannelThreadStatus.OPEN


def _dedupe_warnings(
    warnings: list[BatchValidationWarning],
) -> list[BatchValidationWarning]:
    seen: set[tuple[str, str, tuple[str, ...]]] = set()
    deduped: list[BatchValidationWarning] = []
    for warning in warnings:
        key = (warning.code, warning.message, tuple(warning.package_ids))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(warning)
    return deduped


def _apply_player_visibility(
    warnings: list[BatchValidationWarning],
    *,
    player_entity_id: str,
) -> list[BatchValidationWarning]:
    visible_warnings: list[BatchValidationWarning] = []
    for warning in warnings:
        player_visible = warning.actor_id in {None, player_entity_id}
        visible_warnings.append(warning.model_copy(update={"player_visible": player_visible}))
    return visible_warnings
