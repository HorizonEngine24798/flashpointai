from __future__ import annotations

from datetime import datetime, timezone
import operator
import re

from pydantic import BaseModel, Field

from crisis_room.engine.actions import ActionDefinition, ActionPackage, ActionValidationResult
from crisis_room.engine.clocks import NumericChange, apply_numeric_effects, clamp
from crisis_room.engine.resources import (
    ResourceLedgerEntry,
    apply_resource_effects,
    check_resources,
    merge_requirements,
)
from crisis_room.state.signals import (
    PayloadType,
    Signal,
    SignalChannel,
    SignalVisibility,
)
from crisis_room.state.timelines import TimelineEntry, TimelineScope
from crisis_room.state.world import WorldStateV2


class DeterministicTurnResult(BaseModel):
    world_state: WorldStateV2
    accepted_actions: list[ActionPackage] = Field(default_factory=list)
    rejected_actions: list[ActionPackage] = Field(default_factory=list)
    scheduled_actions: list[ActionPackage] = Field(default_factory=list)
    completed_pending_actions: list[ActionPackage] = Field(default_factory=list)
    emitted_signals: list[Signal] = Field(default_factory=list)
    trace: list[str] = Field(default_factory=list)
    causal_trace: list["CausalTraceEntry"] = Field(default_factory=list)
    validation_results: dict[str, ActionValidationResult] = Field(default_factory=dict)


class CausalTraceEntry(BaseModel):
    turn: int
    phase: str
    action_package_id: str | None = None
    actor_id: str | None = None
    action_id: str | None = None
    summary: str
    details: dict[str, str | int | float | bool] = Field(default_factory=dict)


class DeterministicEngineV2:
    """Catalog-driven deterministic engine for Phase 3."""

    def __init__(self, action_catalog: list[ActionDefinition]) -> None:
        self.action_catalog = {definition.action_id: definition for definition in action_catalog}

    def validate_action(
        self,
        world_state: WorldStateV2,
        action_package: ActionPackage,
        *,
        skip_resource_costs: bool = False,
        skip_cooldown: bool = False,
    ) -> ActionValidationResult:
        errors: list[str] = []
        warnings: list[str] = []
        definition = self.action_catalog.get(action_package.action_id)

        if definition is None:
            errors.append(f"unknown action: {action_package.action_id}")
            return ActionValidationResult(
                is_valid=False,
                errors=errors,
                warnings=warnings,
                action_definition_id=action_package.action_id,
            )

        actor = world_state.actors.get(action_package.actor_id)
        if actor is None:
            errors.append(f"unknown actor: {action_package.actor_id}")
        elif not _actor_type_allowed(actor.entity_type.value, definition.actor_types_allowed):
            errors.append(
                f"actor type {actor.entity_type.value} cannot perform {definition.action_id}"
            )

        if not action_package.intent_summary.strip():
            errors.append("intent summary is empty")

        if definition.channels_allowed and action_package.channel not in definition.channels_allowed:
            allowed = ", ".join(channel.value for channel in definition.channels_allowed)
            errors.append(f"channel {action_package.channel.value} not allowed; allowed: {allowed}")

        target_count = len(action_package.target_ids)
        if target_count < definition.min_targets:
            errors.append(
                f"{definition.action_id} requires at least {definition.min_targets} target(s)"
            )
        if definition.max_targets is not None and target_count > definition.max_targets:
            errors.append(
                f"{definition.action_id} allows at most {definition.max_targets} target(s)"
            )

        for target_id in action_package.target_ids:
            target = world_state.actors.get(target_id)
            if target is None:
                errors.append(f"unknown target: {target_id}")
                continue
            if not _target_allowed(target_id, target.entity_type.value, definition.targets_allowed):
                errors.append(
                    f"target {target_id} of type {target.entity_type.value} "
                    f"not allowed for {definition.action_id}"
                )

        if actor is not None and not skip_resource_costs:
            needed = merge_requirements(definition.required_resources, definition.resource_costs)
            resource_check = check_resources(actor.resources, needed)
            if not resource_check.ok:
                missing = ", ".join(
                    f"{resource} short by {amount}"
                    for resource, amount in resource_check.missing.items()
                )
                errors.append(f"insufficient resources: {missing}")

        cooldown_key = _cooldown_key(action_package.actor_id, definition.action_id)
        cooldown_until = world_state.metadata.get(cooldown_key)
        if (
            not skip_cooldown
            and isinstance(cooldown_until, int)
            and world_state.turn_number < cooldown_until
        ):
            errors.append(
                f"{definition.action_id} is on cooldown until turn {cooldown_until}"
            )

        for precondition in definition.preconditions:
            ok, message = _evaluate_precondition(world_state, action_package, precondition)
            if not ok:
                errors.append(message)

        if not action_package.target_ids and definition.targets_allowed and definition.min_targets == 0:
            warnings.append(f"{definition.action_id} has target rules but no targets")

        return ActionValidationResult(
            is_valid=not errors,
            errors=errors,
            warnings=warnings,
            action_definition_id=definition.action_id,
        )

    def resolve_actions(
        self,
        world_state: WorldStateV2,
        action_packages: list[ActionPackage],
    ) -> DeterministicTurnResult:
        next_world = world_state.model_copy(deep=True)
        result = DeterministicTurnResult(world_state=next_world)

        self._resolve_due_pending_actions(next_world, result)
        for action_package in action_packages:
            self._resolve_submitted_action(next_world, result, action_package)

        result.world_state = next_world
        return result

    def _resolve_due_pending_actions(
        self,
        world_state: WorldStateV2,
        result: DeterministicTurnResult,
    ) -> None:
        remaining: list[ActionPackage] = []
        due: list[ActionPackage] = []
        for pending_action in world_state.pending_actions:
            ready_turn = pending_action.metadata.get("ready_turn")
            if isinstance(ready_turn, int) and ready_turn <= world_state.turn_number:
                due.append(pending_action)
            else:
                remaining.append(pending_action)
        world_state.pending_actions = remaining

        for pending_action in due:
            definition = self.action_catalog.get(pending_action.action_id)
            if definition is None:
                result.rejected_actions.append(pending_action)
                self._trace(
                    result,
                    world_state,
                    "validation",
                    "pending action rejected because its definition is missing",
                    pending_action,
                )
                continue
            validation = self.validate_action(
                world_state,
                pending_action,
                skip_resource_costs=True,
                skip_cooldown=True,
            )
            result.validation_results[pending_action.package_id] = validation
            if not validation.is_valid:
                result.rejected_actions.append(pending_action)
                result.trace.extend(validation.errors)
                self._write_rejection_timeline(world_state, pending_action, validation)
                continue
            self._execute_action(
                world_state,
                result,
                pending_action,
                definition,
                pay_resource_costs=False,
                pending_completion=True,
            )

    def _resolve_submitted_action(
        self,
        world_state: WorldStateV2,
        result: DeterministicTurnResult,
        action_package: ActionPackage,
    ) -> None:
        validation = self.validate_action(world_state, action_package)
        result.validation_results[action_package.package_id] = validation
        if not validation.is_valid:
            result.rejected_actions.append(action_package)
            result.trace.extend(validation.errors)
            self._write_rejection_timeline(world_state, action_package, validation)
            self._trace(
                result,
                world_state,
                "validation",
                "action rejected",
                action_package,
                valid=False,
            )
            return

        definition = self.action_catalog[action_package.action_id]
        delay = definition.preparation_turns + max(0, definition.execution_turns - 1)
        self._apply_submission_costs(world_state, result, action_package, definition)
        self._set_cooldown(world_state, action_package, definition)

        if delay > 0:
            scheduled = action_package.model_copy(deep=True)
            scheduled.metadata.update(
                {
                    "scheduled_by_engine": True,
                    "scheduled_turn": world_state.turn_number,
                    "ready_turn": world_state.turn_number + delay,
                    "resource_costs_paid": True,
                    "action_definition_id": definition.action_id,
                }
            )
            world_state.pending_actions.append(scheduled)
            result.scheduled_actions.append(scheduled)
            self._write_scheduled_timeline(world_state, scheduled, definition)
            self._trace(
                result,
                world_state,
                "scheduling",
                f"scheduled action for turn {scheduled.metadata['ready_turn']}",
                scheduled,
                ready_turn=int(scheduled.metadata["ready_turn"]),
            )
            return

        self._execute_action(
            world_state,
            result,
            action_package,
            definition,
            pay_resource_costs=False,
            pending_completion=False,
        )

    def _execute_action(
        self,
        world_state: WorldStateV2,
        result: DeterministicTurnResult,
        action_package: ActionPackage,
        definition: ActionDefinition,
        *,
        pay_resource_costs: bool,
        pending_completion: bool,
    ) -> None:
        if pay_resource_costs:
            self._apply_submission_costs(world_state, result, action_package, definition)
        actor = world_state.actors[action_package.actor_id]

        resource_entries: list[ResourceLedgerEntry] = []
        resource_entries.extend(
            apply_resource_effects(
                actor.entity_id,
                actor.resources,
                definition.actor_resource_effects,
                reason=f"{definition.action_id}:actor_effect",
            )
        )
        for target_id in action_package.target_ids:
            target = world_state.actors[target_id]
            resource_entries.extend(
                apply_resource_effects(
                    target.entity_id,
                    target.resources,
                    definition.target_resource_effects,
                    reason=f"{definition.action_id}:target_effect",
                )
            )

        truth_changes = apply_numeric_effects(
            world_state.truth_metrics,
            definition.truth_metric_effects,
        )
        public_changes = apply_numeric_effects(
            world_state.public_metrics,
            definition.public_metric_effects,
        )
        clock_changes = apply_numeric_effects(
            world_state.hidden_clocks,
            definition.clock_effects,
        )
        relationship_changes = self._apply_relationship_effects(
            world_state,
            action_package,
            definition,
        )

        signal = self._action_signal(world_state, action_package, definition)
        actor.outbox.append(signal)
        result.emitted_signals.append(signal)
        result.accepted_actions.append(action_package)
        if pending_completion:
            result.completed_pending_actions.append(action_package)

        self._write_execution_timeline(
            world_state,
            action_package,
            definition,
            signal,
            resource_entries,
            truth_changes,
            public_changes,
            clock_changes,
            relationship_changes,
        )
        self._trace(
            result,
            world_state,
            "adjudication",
            f"executed {definition.action_id}",
            action_package,
            emitted_signal_id=signal.signal_id,
        )
        result.trace.append(
            f"executed {action_package.package_id} via {definition.action_id}; "
            f"emitted {signal.signal_id}"
        )

    def _apply_submission_costs(
        self,
        world_state: WorldStateV2,
        result: DeterministicTurnResult,
        action_package: ActionPackage,
        definition: ActionDefinition,
    ) -> None:
        actor = world_state.actors[action_package.actor_id]
        costs = {resource: -amount for resource, amount in definition.resource_costs.items()}
        entries = apply_resource_effects(
            actor.entity_id,
            actor.resources,
            costs,
            reason=f"{definition.action_id}:resource_cost",
        )
        for entry in entries:
            result.trace.append(
                f"resource {entry.entity_id}.{entry.resource}: "
                f"{entry.before}->{entry.after} ({entry.delta})"
            )
            self._trace(
                result,
                world_state,
                "resources",
                f"applied resource cost {entry.resource}",
                action_package,
                resource=entry.resource,
                before=entry.before,
                after=entry.after,
                delta=entry.delta,
            )

    def _set_cooldown(
        self,
        world_state: WorldStateV2,
        action_package: ActionPackage,
        definition: ActionDefinition,
    ) -> None:
        if definition.cooldown_turns <= 0:
            return
        world_state.metadata[_cooldown_key(action_package.actor_id, definition.action_id)] = (
            world_state.turn_number + definition.cooldown_turns
        )

    def _apply_relationship_effects(
        self,
        world_state: WorldStateV2,
        action_package: ActionPackage,
        definition: ActionDefinition,
    ) -> list[NumericChange]:
        changes: list[NumericChange] = []
        for target_id in action_package.target_ids:
            pair_key = f"{action_package.actor_id}->{target_id}"
            pair = world_state.relationships.setdefault(pair_key, {})
            for metric, delta in definition.relationship_effects.items():
                before = float(pair.get(metric, 0.0))
                after = round(clamp(before + float(delta)), 10)
                pair[metric] = after
                changes.append(
                    NumericChange(
                        key=f"{pair_key}.{metric}",
                        before=before,
                        delta=float(delta),
                        after=after,
                    )
                )
        return changes

    def _write_rejection_timeline(
        self,
        world_state: WorldStateV2,
        action_package: ActionPackage,
        validation: ActionValidationResult,
    ) -> None:
        world_state.omniscient_timeline.append(
            TimelineEntry(
                entry_id=f"omn_{world_state.turn_number}_{action_package.package_id}_rejected",
                turn=world_state.turn_number,
                scope=TimelineScope.OMNISCIENT,
                title="Action Rejected",
                summary="; ".join(validation.errors),
                source="deterministic_engine_v2",
                tags=["action", "rejected"],
                created_at=_deterministic_time(world_state.turn_number),
                metadata={"package_id": action_package.package_id},
            )
        )

    def _write_scheduled_timeline(
        self,
        world_state: WorldStateV2,
        action_package: ActionPackage,
        definition: ActionDefinition,
    ) -> None:
        ready_turn = int(action_package.metadata["ready_turn"])
        world_state.omniscient_timeline.append(
            TimelineEntry(
                entry_id=f"omn_{world_state.turn_number}_{action_package.package_id}_scheduled",
                turn=world_state.turn_number,
                scope=TimelineScope.OMNISCIENT,
                title="Action Scheduled",
                summary=(
                    f"{action_package.actor_id} began {definition.title}; "
                    f"effects resolve on turn {ready_turn}."
                ),
                source="deterministic_engine_v2",
                tags=["action", "scheduled", definition.category.value],
                created_at=_deterministic_time(world_state.turn_number),
                metadata={
                    "package_id": action_package.package_id,
                    "ready_turn": ready_turn,
                },
            )
        )

    def _write_execution_timeline(
        self,
        world_state: WorldStateV2,
        action_package: ActionPackage,
        definition: ActionDefinition,
        signal: Signal,
        resource_entries: list[ResourceLedgerEntry],
        truth_changes: list[NumericChange],
        public_changes: list[NumericChange],
        clock_changes: list[NumericChange],
        relationship_changes: list[NumericChange],
    ) -> None:
        actor = world_state.actors[action_package.actor_id]
        world_state.omniscient_timeline.append(
            TimelineEntry(
                entry_id=f"omn_{world_state.turn_number}_{action_package.package_id}_executed",
                turn=world_state.turn_number,
                scope=TimelineScope.OMNISCIENT,
                title=definition.omniscient_timeline_title or "Action Resolved",
                summary=(
                    f"{actor.name} executed {definition.title}: "
                    f"{action_package.intent_summary}"
                ),
                source="deterministic_engine_v2",
                signal_ids=[signal.signal_id],
                tags=["action", "resolved", definition.category.value, action_package.channel.value],
                created_at=_deterministic_time(world_state.turn_number),
                metadata={
                    "package_id": action_package.package_id,
                    "resource_changes": len(resource_entries),
                    "truth_changes": len(truth_changes),
                    "public_changes": len(public_changes),
                    "clock_changes": len(clock_changes),
                    "relationship_changes": len(relationship_changes),
                },
            )
        )
        if signal.visibility == SignalVisibility.PUBLIC:
            world_state.public_timeline.append(
                TimelineEntry(
                    entry_id=f"pub_{world_state.turn_number}_{action_package.package_id}_executed",
                    turn=world_state.turn_number,
                    scope=TimelineScope.PUBLIC,
                    title=definition.public_timeline_title or "Public Action",
                    summary=action_package.public_rationale or action_package.intent_summary,
                    source=action_package.actor_id,
                    signal_ids=[signal.signal_id],
                    tags=["action", "public", definition.category.value],
                    created_at=_deterministic_time(world_state.turn_number),
                    metadata={"package_id": action_package.package_id},
                )
            )

    def _action_signal(
        self,
        world_state: WorldStateV2,
        action_package: ActionPackage,
        definition: ActionDefinition,
    ) -> Signal:
        payload_type = _payload_type_for(action_package.channel, definition)
        visibility = _visibility_for(action_package.channel)
        content = action_package.intent_summary
        if visibility == SignalVisibility.PUBLIC and action_package.public_rationale:
            content = action_package.public_rationale
        elif action_package.private_rationale:
            content = action_package.intent_summary
        return Signal(
            signal_id=(
                f"sig_{world_state.turn_number}_{action_package.package_id}_"
                f"{definition.action_id}"
            ),
            source_entity_id=action_package.actor_id,
            recipient_entity_ids=[] if visibility == SignalVisibility.PUBLIC else action_package.target_ids,
            channel=action_package.channel,
            payload_type=payload_type,
            content=content,
            truth_reference_id=action_package.package_id,
            emitted_turn=world_state.turn_number,
            intended_arrival_turn=world_state.turn_number,
            visibility=visibility,
            reliability=definition.signal_reliability,
            leak_risk=definition.signal_leak_risk,
            distortion_risk=definition.signal_distortion_risk,
            urgency=action_package.commitment_level,
            classification="public" if visibility == SignalVisibility.PUBLIC else "confidential",
            metadata={"action_id": definition.action_id},
        )

    def _trace(
        self,
        result: DeterministicTurnResult,
        world_state: WorldStateV2,
        phase: str,
        summary: str,
        action_package: ActionPackage | None = None,
        **details: str | int | float | bool,
    ) -> None:
        result.causal_trace.append(
            CausalTraceEntry(
                turn=world_state.turn_number,
                phase=phase,
                action_package_id=action_package.package_id if action_package else None,
                actor_id=action_package.actor_id if action_package else None,
                action_id=action_package.action_id if action_package else None,
                summary=summary,
                details=details,
            )
        )


_PRECONDITION_RE = re.compile(
    r"^(?P<scope>truth|public|clock):(?P<key>[A-Za-z0-9_.-]+)"
    r"(?P<op>>=|<=|==|>|<)(?P<value>-?\d+(?:\.\d+)?)$"
)
_OPERATORS = {
    ">=": operator.ge,
    "<=": operator.le,
    ">": operator.gt,
    "<": operator.lt,
    "==": operator.eq,
}


def _actor_type_allowed(actor_type: str, allowed: list[str]) -> bool:
    return not allowed or "*" in allowed or "any" in allowed or actor_type in allowed


def _target_allowed(target_id: str, target_type: str, allowed: list[str]) -> bool:
    return not allowed or "*" in allowed or "any" in allowed or target_id in allowed or target_type in allowed


def _evaluate_precondition(
    world_state: WorldStateV2,
    action_package: ActionPackage,
    precondition: str,
) -> tuple[bool, str]:
    match = _PRECONDITION_RE.match(precondition.replace(" ", ""))
    if not match:
        return False, f"unsupported precondition: {precondition}"
    scope = match.group("scope")
    key = match.group("key")
    op = match.group("op")
    threshold = float(match.group("value"))
    if scope == "truth":
        actual = float(world_state.truth_metrics.get(key, 0.0))
    elif scope == "public":
        actual = float(world_state.public_metrics.get(key, 0.0))
    else:
        actual = float(world_state.hidden_clocks.get(key, 0.0))
    if _OPERATORS[op](actual, threshold):
        return True, ""
    return (
        False,
        f"precondition failed for {action_package.action_id}: "
        f"{scope}:{key} was {actual}, expected {op}{threshold}",
    )


def _payload_type_for(
    channel: SignalChannel,
    definition: ActionDefinition,
) -> PayloadType:
    if definition.information_outputs:
        return definition.information_outputs[0]
    if channel == SignalChannel.PUBLIC:
        return PayloadType.PUBLIC_STATEMENT
    if channel == SignalChannel.BACKCHANNEL:
        return PayloadType.BACKCHANNEL_MESSAGE
    if channel == SignalChannel.INTEL:
        return PayloadType.INTEL_REPORT
    if channel == SignalChannel.MEDIA:
        return PayloadType.MEDIA_REPORT
    if channel == SignalChannel.MILITARY:
        return PayloadType.MILITARY_MOVEMENT_OBSERVATION
    if channel == SignalChannel.ECONOMIC:
        return PayloadType.ECONOMIC_SIGNAL
    if channel == SignalChannel.HUMANITARIAN:
        return PayloadType.HUMANITARIAN_REPORT
    if channel == SignalChannel.RUMOR:
        return PayloadType.RUMOR
    if channel == SignalChannel.GAMEMASTER:
        return PayloadType.GAMEMASTER_RULING
    return PayloadType.PRIVATE_DIPLOMATIC_MESSAGE


def _visibility_for(channel: SignalChannel) -> SignalVisibility:
    if channel in {SignalChannel.PUBLIC, SignalChannel.MEDIA, SignalChannel.RUMOR}:
        return SignalVisibility.PUBLIC
    if channel == SignalChannel.INTEL:
        return SignalVisibility.SECRET
    if channel in {SignalChannel.BACKCHANNEL, SignalChannel.MILITARY}:
        return SignalVisibility.COVERT
    return SignalVisibility.PRIVATE


def _cooldown_key(actor_id: str, action_id: str) -> str:
    return f"cooldown:{actor_id}:{action_id}"


def _deterministic_time(turn_number: int) -> datetime:
    return datetime.fromtimestamp(turn_number, tz=timezone.utc)


class FakeDeterministicEngine:
    """Small deterministic resolver for Phase 1 integration tests and debug TUI."""

    def validate_action(
        self,
        world_state: WorldStateV2,
        action_package: ActionPackage,
    ) -> ActionValidationResult:
        errors: list[str] = []
        if action_package.actor_id not in world_state.actors:
            errors.append(f"unknown actor: {action_package.actor_id}")
        if not action_package.intent_summary.strip():
            errors.append("intent summary is empty")
        missing_targets = [
            target_id
            for target_id in action_package.target_ids
            if target_id not in world_state.actors
        ]
        if missing_targets:
            errors.append(f"unknown target(s): {', '.join(missing_targets)}")
        return ActionValidationResult(is_valid=not errors, errors=errors)

    def resolve_actions(
        self,
        world_state: WorldStateV2,
        action_packages: list[ActionPackage],
    ) -> DeterministicTurnResult:
        next_world = world_state.model_copy(deep=True)
        result = DeterministicTurnResult(world_state=next_world)
        for action_package in action_packages:
            validation = self.validate_action(next_world, action_package)
            if not validation.is_valid:
                result.rejected_actions.append(action_package)
                result.trace.extend(validation.errors)
                continue

            actor = next_world.actors[action_package.actor_id]
            result.accepted_actions.append(action_package)
            next_world.omniscient_timeline.append(
                TimelineEntry(
                    turn=next_world.turn_number,
                    scope=TimelineScope.OMNISCIENT,
                    title="Action Resolved",
                    summary=(
                        f"{actor.name} submitted {action_package.action_id}: "
                        f"{action_package.intent_summary}"
                    ),
                    source="fake_deterministic_engine",
                    tags=["action", action_package.channel.value],
                    metadata={"package_id": action_package.package_id},
                )
            )
            if action_package.channel == SignalChannel.PUBLIC:
                next_world.public_timeline.append(
                    TimelineEntry(
                        turn=next_world.turn_number,
                        scope=TimelineScope.PUBLIC,
                        title="Public Statement",
                        summary=action_package.public_rationale or action_package.intent_summary,
                        source=actor.entity_id,
                        tags=["action", "public"],
                    )
                )

            signal = self._action_signal(next_world, action_package)
            result.emitted_signals.append(signal)
            actor.outbox.append(signal)
            result.trace.append(
                f"accepted {action_package.package_id} and emitted {signal.signal_id}"
            )
        result.world_state = next_world
        return result

    def _action_signal(
        self,
        world_state: WorldStateV2,
        action_package: ActionPackage,
    ) -> Signal:
        is_public = action_package.channel == SignalChannel.PUBLIC
        payload_type = (
            PayloadType.PUBLIC_STATEMENT
            if is_public
            else PayloadType.PRIVATE_DIPLOMATIC_MESSAGE
        )
        visibility = SignalVisibility.PUBLIC if is_public else SignalVisibility.PRIVATE
        recipients = [] if is_public else action_package.target_ids
        return Signal(
            signal_id=f"sig_turn_{world_state.turn_number}_{action_package.package_id}",
            source_entity_id=action_package.actor_id,
            recipient_entity_ids=recipients,
            channel=action_package.channel,
            payload_type=payload_type,
            content=action_package.intent_summary,
            truth_reference_id=action_package.package_id,
            emitted_turn=world_state.turn_number,
            intended_arrival_turn=world_state.turn_number,
            visibility=visibility,
            reliability=1.0,
            leak_risk=0.1 if not is_public else 0.0,
            distortion_risk=0.2 if not is_public else 0.0,
            classification="public" if is_public else "confidential",
        )
