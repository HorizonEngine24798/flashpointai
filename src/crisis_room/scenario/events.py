from __future__ import annotations

from datetime import datetime, timezone
import hashlib

from pydantic import BaseModel, Field

from crisis_room.engine.adjudication import DeterministicTurnResult
from crisis_room.engine.clocks import NumericChange, apply_numeric_effects, clamp
from crisis_room.state.events import ScenarioEventRecord
from crisis_room.state.signals import PayloadType, Signal, SignalChannel, SignalVisibility
from crisis_room.state.timelines import TimelineEntry, TimelineScope
from crisis_room.state.world import WorldStateV2


class ScenarioEventTrigger(BaseModel):
    min_turn: int = Field(default=1, ge=0)
    max_turn: int | None = Field(default=None, ge=0)
    probability: float = Field(default=1.0, ge=0.0, le=1.0)
    once: bool = True
    required_action_ids: list[str] = Field(default_factory=list)
    required_any_action_ids: list[str] = Field(default_factory=list)
    excluded_action_ids: list[str] = Field(default_factory=list)
    truth_metric_minimums: dict[str, float] = Field(default_factory=dict)
    truth_metric_maximums: dict[str, float] = Field(default_factory=dict)
    public_metric_minimums: dict[str, float] = Field(default_factory=dict)
    public_metric_maximums: dict[str, float] = Field(default_factory=dict)
    hidden_clock_minimums: dict[str, float] = Field(default_factory=dict)
    hidden_clock_maximums: dict[str, float] = Field(default_factory=dict)


class ScenarioEventEffect(BaseModel):
    truth_metric_effects: dict[str, float] = Field(default_factory=dict)
    public_metric_effects: dict[str, float] = Field(default_factory=dict)
    clock_effects: dict[str, float] = Field(default_factory=dict)
    relationship_effects: dict[str, dict[str, float]] = Field(default_factory=dict)
    active_commitments_added: list[str] = Field(default_factory=list)


class ScenarioEventSignalDefinition(BaseModel):
    target_entity_ids: list[str] = Field(default_factory=list)
    channel: SignalChannel = SignalChannel.GAMEMASTER
    payload_type: PayloadType = PayloadType.EVENT_NOTICE
    content: str
    visibility: SignalVisibility = SignalVisibility.PRIVATE
    reliability: float = Field(default=0.8, ge=0.0, le=1.0)
    leak_risk: float = Field(default=0.0, ge=0.0, le=1.0)
    distortion_risk: float = Field(default=0.1, ge=0.0, le=1.0)
    urgency: float = Field(default=0.6, ge=0.0, le=1.0)
    classification: str = "confidential"
    leak_summary: str = ""


class ScenarioEventDefinition(BaseModel):
    event_id: str
    title: str
    summary: str
    kind: str = "scenario"
    enabled: bool = True
    trigger: ScenarioEventTrigger = Field(default_factory=ScenarioEventTrigger)
    effects: ScenarioEventEffect = Field(default_factory=ScenarioEventEffect)
    signals: list[ScenarioEventSignalDefinition] = Field(default_factory=list)
    visible_to: list[str] = Field(default_factory=list)
    related_entity_ids: list[str] = Field(default_factory=list)
    related_action_ids: list[str] = Field(default_factory=list)
    problem_title: str = ""
    problem_summary: str = ""
    urgency: str = "medium"
    visible_duration_turns: int = Field(default=2, ge=0)
    public_timeline_title: str = ""
    public_timeline_summary: str = ""


class ScenarioEventResolution(BaseModel):
    world_state: WorldStateV2
    fired_events: list[ScenarioEventRecord] = Field(default_factory=list)
    emitted_signals: list[Signal] = Field(default_factory=list)
    no_event_reason: str = ""
    trace: list[str] = Field(default_factory=list)
    framing_summary: str = ""


def resolve_scenario_events(
    world_state: WorldStateV2,
    event_library: list[ScenarioEventDefinition],
    *,
    deterministic_result: DeterministicTurnResult | None = None,
    player_entity_id: str = "",
    framing_summary: str = "",
    max_events: int = 1,
) -> ScenarioEventResolution:
    next_world = world_state.model_copy(deep=True)
    result = ScenarioEventResolution(
        world_state=next_world,
        framing_summary=framing_summary,
    )
    if not event_library:
        result.no_event_reason = "no scenario event library configured"
        result.trace.append(result.no_event_reason)
        return result

    action_ids = _turn_action_ids(deterministic_result)
    fired_count = 0
    for event in event_library:
        if fired_count >= max_events:
            break
        ok, reason = _event_is_eligible(next_world, event, action_ids)
        if not ok:
            result.trace.append(f"{event.event_id}: skipped ({reason})")
            continue
        roll = _score(next_world, event.event_id, "event_roll")
        if roll > event.trigger.probability:
            result.trace.append(
                f"{event.event_id}: no event (roll {roll:.3f} > {event.trigger.probability:.3f})"
            )
            continue
        _fire_event(
            next_world,
            event,
            result,
            player_entity_id=player_entity_id,
            action_ids=action_ids,
        )
        fired_count += 1

    if not result.fired_events:
        result.no_event_reason = "no authored scenario event fired"
    result.world_state = next_world
    return result


def _event_is_eligible(
    world_state: WorldStateV2,
    event: ScenarioEventDefinition,
    action_ids: set[str],
) -> tuple[bool, str]:
    if not event.enabled:
        return False, "disabled"
    turn = world_state.turn_number
    trigger = event.trigger
    if turn < trigger.min_turn:
        return False, f"turn {turn} before {trigger.min_turn}"
    if trigger.max_turn is not None and turn > trigger.max_turn:
        return False, f"turn {turn} after {trigger.max_turn}"
    if trigger.once and any(record.event_id == event.event_id for record in world_state.event_history):
        return False, "already fired"
    required = set(trigger.required_action_ids)
    if required and not required.issubset(action_ids):
        return False, "required actions missing"
    any_required = set(trigger.required_any_action_ids)
    if any_required and not any_required.intersection(action_ids):
        return False, "no required action match"
    excluded = set(trigger.excluded_action_ids)
    if excluded.intersection(action_ids):
        return False, "excluded action present"
    if not _metric_bounds_ok(world_state.truth_metrics, trigger.truth_metric_minimums, trigger.truth_metric_maximums):
        return False, "truth metric bounds failed"
    if not _metric_bounds_ok(world_state.public_metrics, trigger.public_metric_minimums, trigger.public_metric_maximums):
        return False, "public metric bounds failed"
    if not _metric_bounds_ok(world_state.hidden_clocks, trigger.hidden_clock_minimums, trigger.hidden_clock_maximums):
        return False, "hidden clock bounds failed"
    return True, ""


def _fire_event(
    world_state: WorldStateV2,
    event: ScenarioEventDefinition,
    result: ScenarioEventResolution,
    *,
    player_entity_id: str,
    action_ids: set[str],
) -> None:
    effect_summary: list[str] = []
    effect_summary.extend(
        _change_summaries(
            "truth",
            apply_numeric_effects(world_state.truth_metrics, event.effects.truth_metric_effects),
        )
    )
    effect_summary.extend(
        _change_summaries(
            "public",
            apply_numeric_effects(world_state.public_metrics, event.effects.public_metric_effects),
        )
    )
    effect_summary.extend(
        _change_summaries(
            "clock",
            apply_numeric_effects(world_state.hidden_clocks, event.effects.clock_effects),
        )
    )
    effect_summary.extend(_apply_relationship_effects(world_state, event.effects.relationship_effects))
    for commitment in event.effects.active_commitments_added:
        if commitment not in world_state.active_commitments:
            world_state.active_commitments.append(commitment)
            effect_summary.append(f"commitment added: {commitment}")

    signals = _event_signals(world_state, event)
    result.emitted_signals.extend(signals)
    signal_ids = [signal.signal_id for signal in signals]
    record = ScenarioEventRecord(
        event_id=event.event_id,
        title=event.title,
        summary=event.summary,
        kind=event.kind,
        turn_number=world_state.turn_number,
        expires_turn=world_state.turn_number + event.visible_duration_turns,
        urgency=event.urgency,
        visible_to=_visible_to(event, player_entity_id),
        related_entity_ids=event.related_entity_ids,
        related_action_ids=sorted(set(event.related_action_ids).union(action_ids)),
        problem_title=event.problem_title or event.title,
        problem_summary=event.problem_summary or event.summary,
        effect_summary=effect_summary,
        signal_ids=signal_ids,
        public=bool(event.public_timeline_title),
        metadata={
            "signal_count": len(signals),
            "framing_available": bool(result.framing_summary),
        },
    )
    world_state.event_history.append(record)
    result.fired_events.append(record)
    _append_event_timelines(world_state, event, record, signal_ids)
    result.trace.append(f"{event.event_id}: fired")


def _event_signals(
    world_state: WorldStateV2,
    event: ScenarioEventDefinition,
) -> list[Signal]:
    signals: list[Signal] = []
    for index, definition in enumerate(event.signals, start=1):
        metadata: dict[str, str | int | float | bool] = {
            "scenario_event_id": event.event_id,
            "scenario_event_kind": event.kind,
        }
        if definition.leak_summary:
            metadata["leak_summary"] = definition.leak_summary
        signals.append(
            Signal(
                signal_id=f"event_{world_state.turn_number}_{event.event_id}_{index}",
                source_entity_id="event_creator",
                recipient_entity_ids=definition.target_entity_ids,
                channel=definition.channel,
                payload_type=definition.payload_type,
                content=definition.content,
                truth_reference_id=event.event_id,
                emitted_turn=world_state.turn_number,
                intended_arrival_turn=world_state.turn_number,
                visibility=definition.visibility,
                reliability=definition.reliability,
                leak_risk=definition.leak_risk,
                distortion_risk=definition.distortion_risk,
                urgency=definition.urgency,
                classification=definition.classification,
                metadata=metadata,
            )
        )
    return signals


def _append_event_timelines(
    world_state: WorldStateV2,
    event: ScenarioEventDefinition,
    record: ScenarioEventRecord,
    signal_ids: list[str],
) -> None:
    world_state.omniscient_timeline.append(
        TimelineEntry(
            entry_id=f"omn_event_{world_state.turn_number}_{event.event_id}",
            turn=world_state.turn_number,
            scope=TimelineScope.OMNISCIENT,
            title=event.title,
            summary=event.summary,
            source="scenario_event_resolver",
            signal_ids=signal_ids,
            tags=["scenario_event", event.kind, event.event_id],
            created_at=_deterministic_time(world_state.turn_number),
            metadata={
                "event_id": event.event_id,
                "effect_count": len(record.effect_summary),
                "signal_count": len(signal_ids),
            },
        )
    )
    if event.public_timeline_title:
        world_state.public_timeline.append(
            TimelineEntry(
                entry_id=f"public_event_{world_state.turn_number}_{event.event_id}",
                turn=world_state.turn_number,
                scope=TimelineScope.PUBLIC,
                title=event.public_timeline_title,
                summary=event.public_timeline_summary or event.summary,
                source="scenario_event_resolver",
                signal_ids=signal_ids,
                tags=["scenario_event", "public", event.kind],
                created_at=_deterministic_time(world_state.turn_number),
                metadata={"event_id": event.event_id},
            )
        )


def _turn_action_ids(deterministic_result: DeterministicTurnResult | None) -> set[str]:
    if deterministic_result is None:
        return set()
    return {
        package.action_id
        for package in [
            *deterministic_result.accepted_actions,
            *deterministic_result.scheduled_actions,
            *deterministic_result.completed_pending_actions,
        ]
    }


def _metric_bounds_ok(
    values: dict[str, float],
    minimums: dict[str, float],
    maximums: dict[str, float],
) -> bool:
    for key, minimum in minimums.items():
        if float(values.get(key, 0.0)) < minimum:
            return False
    for key, maximum in maximums.items():
        if float(values.get(key, 0.0)) > maximum:
            return False
    return True


def _apply_relationship_effects(
    world_state: WorldStateV2,
    effects: dict[str, dict[str, float]],
) -> list[str]:
    lines: list[str] = []
    for pair_key, metric_effects in effects.items():
        pair = world_state.relationships.setdefault(pair_key, {})
        changes = []
        for key, delta in metric_effects.items():
            before = float(pair.get(key, 0.0))
            after = round(clamp(before + float(delta)), 10)
            pair[key] = after
            changes.append(NumericChange(key=f"{pair_key}.{key}", before=before, delta=float(delta), after=after))
        lines.extend(_change_summaries("relationship", changes))
    return lines


def _change_summaries(scope: str, changes: list[NumericChange]) -> list[str]:
    lines: list[str] = []
    for change in changes:
        if abs(change.delta) < 0.001:
            continue
        direction = "rose" if change.delta > 0 else "fell"
        lines.append(
            f"{scope}:{change.key} {direction} from {change.before:.2f} to {change.after:.2f}"
        )
    return lines


def _visible_to(event: ScenarioEventDefinition, player_entity_id: str) -> list[str]:
    visible_to = list(event.visible_to)
    if not visible_to and player_entity_id:
        visible_to.append(player_entity_id)
    return visible_to


def _score(world_state: WorldStateV2, event_id: str, purpose: str) -> float:
    material = f"{world_state.rng_seed}:{world_state.turn_number}:{event_id}:{purpose}"
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return int(digest[:12], 16) / float(0xFFFFFFFFFFFF)


def _deterministic_time(turn_number: int) -> datetime:
    return datetime.fromtimestamp(turn_number, tz=timezone.utc)
