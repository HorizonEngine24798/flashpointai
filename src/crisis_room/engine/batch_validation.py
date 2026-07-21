from __future__ import annotations

from collections import defaultdict
from enum import Enum

from pydantic import BaseModel, Field

from crisis_room.config.gameplay import (
    NORMAL_ACTION_BUDGET,
    PUBLIC_COVERT_DEESCALATION_THRESHOLD,
    PUBLIC_COVERT_ESCALATION_THRESHOLD,
)
from crisis_room.engine.actions import (
    ActionDefinition,
    ActionPackage,
    ActionResolver,
    ScenarioCapability,
)
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
    capabilities: list[ScenarioCapability] | None = None,
    action_budget: int = NORMAL_ACTION_BUDGET,
) -> BatchValidationReport:
    resolver = ActionResolver(action_catalog, capabilities)
    warnings: list[BatchValidationWarning] = []
    warnings.extend(
        _action_budget_warnings(
            action_packages,
            player_entity_id=player_entity_id,
            action_budget=action_budget,
        )
    )
    warnings.extend(
        _agenda_shape_warnings(
            action_packages,
            resolver,
            player_entity_id=player_entity_id,
        )
    )
    warnings.extend(_resource_contention_warnings(world_state, action_packages, resolver))
    warnings.extend(_public_covert_pairing_warnings(action_packages, resolver))
    warnings.extend(
        _backchannel_channel_warnings(
            world_state,
            action_packages,
            resolver,
            player_entity_id=player_entity_id,
        )
    )
    return BatchValidationReport(
        warnings=_apply_player_visibility(
            _dedupe_warnings(warnings),
            player_entity_id=player_entity_id,
        )
    )


def format_batch_warning(warning: BatchValidationWarning) -> str:
    return warning.message


def _action_budget_warnings(
    action_packages: list[ActionPackage],
    *,
    player_entity_id: str,
    action_budget: int,
) -> list[BatchValidationWarning]:
    player_packages = [
        package for package in action_packages if package.actor_id == player_entity_id
    ]
    if len(player_packages) <= action_budget:
        return []
    return [
        BatchValidationWarning(
            code="action_budget_exceeded",
            actor_id=player_entity_id,
            action_ids=[package.mechanical_id for package in player_packages],
            package_ids=[package.package_id for package in player_packages],
            message=(
                f"{player_entity_id} queued {len(player_packages)} formal actions; "
                f"the normal budget is {action_budget}."
            ),
        )
    ]


def _agenda_shape_warnings(
    action_packages: list[ActionPackage],
    resolver: ActionResolver,
    *,
    player_entity_id: str,
) -> list[BatchValidationWarning]:
    player_packages = [
        package for package in action_packages if package.actor_id == player_entity_id
    ]
    if len(player_packages) < 2:
        return []
    categories: dict[str, list[ActionPackage]] = defaultdict(list)
    for package in player_packages:
        definition = _resolve(resolver, package)
        if definition is None:
            continue
        categories[definition.category.value].append(package)
    if not categories:
        return []
    category, packages = max(categories.items(), key=lambda item: len(item[1]))
    if len(packages) < len(player_packages):
        return []
    return [
        BatchValidationWarning(
            code="agenda_shape_concentrated",
            severity=BatchWarningSeverity.INFO,
            actor_id=player_entity_id,
            action_ids=[package.mechanical_id for package in packages],
            package_ids=[package.package_id for package in packages],
            message=(
                f"All compiled player actions are {category}; that can be valid, "
                "but it narrows this turn's agenda shape."
            ),
        )
    ]


def _resource_contention_warnings(
    world_state: WorldStateV2,
    action_packages: list[ActionPackage],
    resolver: ActionResolver,
) -> list[BatchValidationWarning]:
    by_actor_resource: dict[tuple[str, str], list[ActionPackage]] = defaultdict(list)
    totals: dict[tuple[str, str], int] = defaultdict(int)
    for package in action_packages:
        definition = _resolve(resolver, package)
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
            _definition_title(resolver, package)
            for package in packages
        ]
        warnings.append(
            BatchValidationWarning(
                code="resource_contention",
                actor_id=actor_id,
                action_ids=[package.mechanical_id for package in packages],
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
    resolver: ActionResolver,
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
            _definition_risk(resolver, package) >= PUBLIC_COVERT_ESCALATION_THRESHOLD
            for package in public_packages
        )
        covert_deescalatory = any(
            _definition_deescalation(resolver, package)
            >= PUBLIC_COVERT_DEESCALATION_THRESHOLD
            for package in covert_packages
        )
        if not public_escalatory or not covert_deescalatory:
            continue
        packages_to_report = [*public_packages, *covert_packages]
        warnings.append(
            BatchValidationWarning(
                code="public_covert_tension",
                actor_id=actor_id,
                action_ids=[package.mechanical_id for package in packages_to_report],
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
    resolver: ActionResolver,
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
            definition = _resolve(resolver, package)
            if definition is not None and "opens_backchannel" in definition.event_hooks:
                continue
            warnings.append(
                BatchValidationWarning(
                    code="missing_backchannel_thread",
                    actor_id=package.actor_id,
                    action_ids=[package.mechanical_id],
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


def _resource_spend(definition: ActionDefinition) -> dict[str, int]:
    spend = dict(definition.resource_costs)
    effect_spend = {
        resource: abs(delta)
        for resource, delta in definition.actor_resource_effects.items()
        if delta < 0
    }
    return merge_requirements(spend, effect_spend)


def _definition_risk(
    resolver: ActionResolver,
    package: ActionPackage,
) -> float:
    definition = _resolve(resolver, package)
    return definition.escalation_risk if definition is not None else 0.0


def _definition_deescalation(
    resolver: ActionResolver,
    package: ActionPackage,
) -> float:
    definition = _resolve(resolver, package)
    return definition.deescalation_potential if definition is not None else 0.0


def _resolve(
    resolver: ActionResolver,
    package: ActionPackage,
) -> ActionDefinition | None:
    definition, errors = resolver.resolve_package(package)
    return None if errors else definition


def _definition_title(
    resolver: ActionResolver,
    package: ActionPackage,
) -> str:
    definition = _resolve(resolver, package)
    return definition.title if definition is not None else package.mechanical_id


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
