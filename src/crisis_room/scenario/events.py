from __future__ import annotations

from datetime import datetime, timezone
import hashlib

from pydantic import BaseModel, Field

from crisis_room.agents.info_channel import RoutingResult
from crisis_room.engine.adjudication import DeterministicTurnResult
from crisis_room.engine.clocks import NumericChange, apply_numeric_effects, clamp
from crisis_room.llm.task_contracts import EventCandidate, SignalCandidate
from crisis_room.scenario.event_choices import expire_event_choices
from crisis_room.state.events import (
    EventChoiceOption,
    ScenarioEventChoiceRecord,
    ScenarioEventRecord,
)
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
    required_any_leaked_signal_action_ids: list[str] = Field(default_factory=list)
    required_any_leaked_signal_capability_ids: list[str] = Field(default_factory=list)
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


class ScenarioEventChoiceDefinition(BaseModel):
    choice_id: str
    prompt: str
    options: list[EventChoiceOption] = Field(default_factory=list)
    visible_to: list[str] = Field(default_factory=list)
    expires_after_turns: int = Field(default=1, ge=0)


class ScenarioEventSettings(BaseModel):
    base_max_events_per_turn: int = Field(default=1, ge=0)
    high_pressure_max_events_per_turn: int = Field(default=2, ge=0)
    action_density_bonus_threshold: int = Field(default=3, ge=0)
    escalation_pressure_threshold: float = Field(default=0.65, ge=0.0, le=1.0)
    allow_llm_event_candidates: bool = False
    llm_candidate_min_plausibility: float = Field(default=0.62, ge=0.0, le=1.0)
    llm_candidate_min_escalation_pressure: float = Field(default=0.55, ge=0.0, le=1.0)
    llm_candidate_effect_clamp: float = Field(default=0.03, ge=0.0, le=1.0)


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
    choices: list[ScenarioEventChoiceDefinition] = Field(default_factory=list)


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
    routing_result: RoutingResult | None = None,
    player_entity_id: str = "",
    framing_summary: str = "",
    max_events: int | None = None,
    event_settings: ScenarioEventSettings | None = None,
    event_candidate: EventCandidate | None = None,
) -> ScenarioEventResolution:
    next_world = world_state.model_copy(deep=True)
    expire_event_choices(next_world)
    result = ScenarioEventResolution(
        world_state=next_world,
        framing_summary=framing_summary,
    )
    settings = event_settings or ScenarioEventSettings()
    event_limit = (
        max_events
        if max_events is not None
        else _event_limit(next_world, settings, deterministic_result)
    )
    if not event_library and event_candidate is None:
        result.no_event_reason = "no scenario event library configured"
        result.trace.append(result.no_event_reason)
        return result

    action_ids = _turn_action_ids(deterministic_result)
    leaked_action_ids = _turn_leaked_signal_action_ids(routing_result)
    leaked_capability_ids = _turn_leaked_signal_capability_ids(routing_result)
    fired_count = 0
    for event in event_library:
        if fired_count >= event_limit:
            break
        ok, reason = _event_is_eligible(
            next_world,
            event,
            action_ids,
            leaked_action_ids=leaked_action_ids,
            leaked_capability_ids=leaked_capability_ids,
        )
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
    if event_candidate is not None and fired_count < event_limit:
        candidate_event, reason = _approved_candidate_event(
            next_world,
            event_candidate,
            settings,
            deterministic_result=deterministic_result,
            player_entity_id=player_entity_id,
        )
        if candidate_event is None:
            result.trace.append(f"llm_candidate:{event_candidate.candidate_id}: rejected ({reason})")
        else:
            _fire_event(
                next_world,
                candidate_event,
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
    *,
    leaked_action_ids: set[str],
    leaked_capability_ids: set[str],
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
    any_leaked_actions = set(trigger.required_any_leaked_signal_action_ids)
    if any_leaked_actions and not any_leaked_actions.intersection(leaked_action_ids):
        return False, "no leaked action match"
    any_leaked_capabilities = set(trigger.required_any_leaked_signal_capability_ids)
    if any_leaked_capabilities and not any_leaked_capabilities.intersection(
        leaked_capability_ids
    ):
        return False, "no leaked capability match"
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
    choice_records = _event_choice_records(world_state, event, player_entity_id)
    world_state.pending_event_choices.extend(choice_records)
    choice_ids = [choice.choice_id for choice in choice_records]
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
        choice_ids=choice_ids,
        public=bool(event.public_timeline_title),
        metadata={
            "signal_count": len(signals),
            "choice_count": len(choice_records),
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
                "choice_count": len(record.choice_ids),
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
        package.mechanical_id
        for package in [
            *deterministic_result.accepted_actions,
            *deterministic_result.scheduled_actions,
            *deterministic_result.completed_pending_actions,
        ]
    }


def _turn_action_count(deterministic_result: DeterministicTurnResult | None) -> int:
    if deterministic_result is None:
        return 0
    return len(
        [
            *deterministic_result.accepted_actions,
            *deterministic_result.scheduled_actions,
            *deterministic_result.completed_pending_actions,
        ]
    )


def _event_limit(
    world_state: WorldStateV2,
    settings: ScenarioEventSettings,
    deterministic_result: DeterministicTurnResult | None,
) -> int:
    limit = settings.base_max_events_per_turn
    action_count = _turn_action_count(deterministic_result)
    escalation = max(
        float(world_state.truth_metrics.get("escalation_pressure", 0.0)),
        float(world_state.hidden_clocks.get("nuclear_escalation", 0.0)),
    )
    if (
        action_count >= settings.action_density_bonus_threshold
        or escalation >= settings.escalation_pressure_threshold
    ):
        limit = max(limit, settings.high_pressure_max_events_per_turn)
    return max(0, limit)


def _approved_candidate_event(
    world_state: WorldStateV2,
    candidate: EventCandidate,
    settings: ScenarioEventSettings,
    *,
    deterministic_result: DeterministicTurnResult | None,
    player_entity_id: str,
) -> tuple[ScenarioEventDefinition | None, str]:
    if not settings.allow_llm_event_candidates:
        return None, "llm candidates disabled"
    event_id = _candidate_event_id(candidate.candidate_id)
    if any(record.event_id == event_id for record in world_state.event_history):
        return None, "candidate already recorded"
    if candidate.plausibility < settings.llm_candidate_min_plausibility:
        return None, "plausibility below threshold"
    action_count = _turn_action_count(deterministic_result)
    escalation = max(
        float(world_state.truth_metrics.get("escalation_pressure", 0.0)),
        float(world_state.hidden_clocks.get("nuclear_escalation", 0.0)),
    )
    pressure_ok = (
        candidate.escalation_pressure >= settings.llm_candidate_min_escalation_pressure
        or action_count >= settings.action_density_bonus_threshold
        or escalation >= settings.escalation_pressure_threshold
    )
    if not pressure_ok:
        return None, "event pressure below threshold"
    known_entity_ids = set(world_state.actors)
    unknown_targets = [
        target_id
        for target_id in candidate.target_entity_ids
        if target_id not in known_entity_ids
    ]
    if unknown_targets:
        return None, "unknown candidate targets: " + ", ".join(unknown_targets)
    for signal in candidate.suggested_signals:
        unknown_signal_targets = [
            target_id
            for target_id in signal.target_entity_ids
            if target_id not in known_entity_ids
        ]
        if unknown_signal_targets:
            return None, "unknown signal targets: " + ", ".join(unknown_signal_targets)

    effects = _candidate_effects(world_state, candidate, settings)
    signals = [
        _candidate_signal_definition(signal, candidate.target_entity_ids)
        for signal in candidate.suggested_signals
    ]
    if not signals:
        signals = [
            ScenarioEventSignalDefinition(
                target_entity_ids=[player_entity_id] if player_entity_id else [],
                channel=SignalChannel.GAMEMASTER,
                payload_type=PayloadType.EVENT_NOTICE,
                content=f"{candidate.title}: {candidate.summary}",
                visibility=SignalVisibility.PRIVATE,
                reliability=candidate.plausibility,
                urgency=candidate.escalation_pressure,
            )
        ]
    public = any(signal.visibility == SignalVisibility.PUBLIC for signal in signals)
    return (
        ScenarioEventDefinition(
            event_id=event_id,
            title=candidate.title,
            summary=candidate.summary,
            kind=f"llm_{candidate.kind.value}",
            trigger=ScenarioEventTrigger(once=True),
            effects=effects,
            signals=signals,
            visible_to=candidate.target_entity_ids or ([player_entity_id] if player_entity_id else []),
            related_entity_ids=candidate.target_entity_ids,
            problem_title=candidate.title,
            problem_summary=candidate.summary,
            urgency=_candidate_urgency(candidate.escalation_pressure),
            public_timeline_title=candidate.title if public else "",
            public_timeline_summary=candidate.summary if public else "",
        ),
        "approved",
    )


def _candidate_event_id(candidate_id: str) -> str:
    cleaned = "".join(
        char if char.isalnum() or char in {"_", "-"} else "_"
        for char in candidate_id.strip().lower()
    ).strip("_")
    return f"llm_candidate_{cleaned or 'event'}"


def _candidate_effects(
    world_state: WorldStateV2,
    candidate: EventCandidate,
    settings: ScenarioEventSettings,
) -> ScenarioEventEffect:
    truth_effects: dict[str, float] = {}
    public_effects: dict[str, float] = {}
    clock_effects: dict[str, float] = {}
    for key, raw_delta in candidate.deterministic_effect_hints.items():
        delta = max(
            -settings.llm_candidate_effect_clamp,
            min(settings.llm_candidate_effect_clamp, float(raw_delta)),
        )
        if key in world_state.public_metrics:
            public_effects[key] = delta
        elif key in world_state.hidden_clocks:
            clock_effects[key] = delta
        elif key in world_state.truth_metrics:
            truth_effects[key] = delta
    return ScenarioEventEffect(
        truth_metric_effects=truth_effects,
        public_metric_effects=public_effects,
        clock_effects=clock_effects,
    )


def _candidate_signal_definition(
    signal: SignalCandidate,
    fallback_targets: list[str],
) -> ScenarioEventSignalDefinition:
    return ScenarioEventSignalDefinition(
        target_entity_ids=signal.target_entity_ids or fallback_targets,
        channel=signal.channel,
        payload_type=signal.payload_type,
        content=signal.content,
        visibility=signal.visibility,
        reliability=signal.reliability,
        leak_risk=signal.leak_risk,
        distortion_risk=signal.distortion_risk,
        urgency=signal.urgency,
        classification=signal.classification,
    )


def _candidate_urgency(escalation_pressure: float) -> str:
    if escalation_pressure >= 0.78:
        return "critical"
    if escalation_pressure >= 0.62:
        return "high"
    if escalation_pressure >= 0.42:
        return "medium"
    return "low"


def _event_choice_records(
    world_state: WorldStateV2,
    event: ScenarioEventDefinition,
    player_entity_id: str,
) -> list[ScenarioEventChoiceRecord]:
    records: list[ScenarioEventChoiceRecord] = []
    for definition in event.choices:
        choice_id = f"{event.event_id}:{definition.choice_id}:{world_state.turn_number}"
        visible_to = list(definition.visible_to) or _visible_to(event, player_entity_id)
        records.append(
            ScenarioEventChoiceRecord(
                choice_id=choice_id,
                event_id=event.event_id,
                title=event.title,
                prompt=definition.prompt,
                turn_number=world_state.turn_number,
                expires_turn=world_state.turn_number + definition.expires_after_turns,
                visible_to=visible_to,
                options=[option.model_copy(deep=True) for option in definition.options],
                metadata={"option_count": len(definition.options)},
            )
        )
    return records


def _turn_leaked_signal_action_ids(routing_result: RoutingResult | None) -> set[str]:
    if routing_result is None:
        return set()
    return {
        str(signal.metadata["action_id"])
        for signal in routing_result.leaked_signals
        if signal.metadata.get("action_id")
    }


def _turn_leaked_signal_capability_ids(routing_result: RoutingResult | None) -> set[str]:
    if routing_result is None:
        return set()
    return {
        str(signal.metadata["capability_id"])
        for signal in routing_result.leaked_signals
        if signal.metadata.get("capability_id")
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
