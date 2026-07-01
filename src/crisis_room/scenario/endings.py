from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from crisis_room.state.endings import EndingOfferRecord, EndingOfferStatus
from crisis_room.state.events import (
    ScenarioEventRecord,
    ScenarioEventStatus,
)
from crisis_room.state.timelines import TimelineEntry, TimelineScope
from crisis_room.state.world import WorldStateV2


class ScenarioEndingDefinition(BaseModel):
    ending_id: str
    title: str
    summary: str
    enabled: bool = True
    priority: int = 0
    min_turn: int = Field(default=1, ge=0)
    max_turn: int | None = Field(default=None, ge=0)
    truth_metric_minimums: dict[str, float] = Field(default_factory=dict)
    truth_metric_maximums: dict[str, float] = Field(default_factory=dict)
    public_metric_minimums: dict[str, float] = Field(default_factory=dict)
    public_metric_maximums: dict[str, float] = Field(default_factory=dict)
    hidden_clock_minimums: dict[str, float] = Field(default_factory=dict)
    hidden_clock_maximums: dict[str, float] = Field(default_factory=dict)
    required_active_commitments: list[str] = Field(default_factory=list)
    required_event_ids: list[str] = Field(default_factory=list)
    excluded_event_ids: list[str] = Field(default_factory=list)
    visible_to: list[str] = Field(default_factory=list)
    related_entity_ids: list[str] = Field(default_factory=list)
    urgency: str = "high"
    reoffer_delay_turns: int = Field(default=3, ge=0)
    public_timeline_title: str = ""
    public_timeline_summary: str = ""
    final_summary: str = ""


class EndingEvaluation(BaseModel):
    world_state: WorldStateV2
    offered_ending: ScenarioEndingDefinition | None = None
    offer_record: EndingOfferRecord | None = None
    event_record: ScenarioEventRecord | None = None
    trace: list[str] = Field(default_factory=list)


class EndingDecisionResult(BaseModel):
    world_state: WorldStateV2
    offer_record: EndingOfferRecord | None = None
    accepted: bool = False
    rejected: bool = False
    errors: list[str] = Field(default_factory=list)
    summary: str = ""


def evaluate_ending_events(
    world_state: WorldStateV2,
    ending_library: list[ScenarioEndingDefinition],
    *,
    player_entity_id: str,
) -> EndingEvaluation:
    next_world = world_state.model_copy(deep=True)
    result = EndingEvaluation(world_state=next_world)
    if not ending_library:
        result.trace.append("no scenario ending library configured")
        return result
    if next_world.accepted_ending_id:
        result.trace.append(f"ending already accepted: {next_world.accepted_ending_id}")
        return result
    active_offer = _active_ending_offer(next_world, player_entity_id)
    if active_offer is not None:
        result.trace.append(f"active ending offer pending: {active_offer.ending_id}")
        return result

    for ending in sorted(ending_library, key=lambda item: (-item.priority, item.ending_id)):
        ok, reason = _ending_is_eligible(next_world, ending)
        if not ok:
            result.trace.append(f"{ending.ending_id}: skipped ({reason})")
            continue
        offer = _build_offer(next_world, ending, player_entity_id)
        event_record = _build_event_record(next_world, ending, offer)
        offer.event_record_id = event_record.event_id
        next_world.ending_offers.append(offer)
        next_world.event_history.append(event_record)
        _append_ending_timelines(next_world, ending, event_record)
        result.offered_ending = ending
        result.offer_record = offer
        result.event_record = event_record
        result.trace.append(f"{ending.ending_id}: offered")
        break

    return result


def active_ending_offers(
    world_state: WorldStateV2,
    *,
    player_entity_id: str,
) -> list[EndingOfferRecord]:
    return [
        offer
        for offer in world_state.ending_offers
        if offer.active_for(world_state.turn_number, player_entity_id)
    ]


def render_active_ending_offers(
    world_state: WorldStateV2,
    *,
    player_entity_id: str,
) -> str:
    offers = active_ending_offers(world_state, player_entity_id=player_entity_id)
    if not offers:
        return "No ending offer is currently active."
    lines = ["ENDING OFFERS"]
    for offer in offers:
        lines.append(f"- {offer.title} ({offer.ending_id})")
        lines.append(f"  {offer.summary}")
        lines.append("  Use ACCEPT ENDING to conclude, or REJECT ENDING to continue.")
    return "\n".join(lines)


def accept_ending_offer(
    world_state: WorldStateV2,
    *,
    player_entity_id: str,
    offer_query: str = "latest",
) -> EndingDecisionResult:
    next_world = world_state.model_copy(deep=True)
    offer = _find_active_ending_offer(
        next_world,
        player_entity_id=player_entity_id,
        offer_query=offer_query,
    )
    if offer is None:
        return EndingDecisionResult(
            world_state=next_world,
            errors=[f"active ending offer not found: {offer_query}"],
        )
    offer.status = EndingOfferStatus.ACCEPTED
    offer.accepted_turn = next_world.turn_number
    next_world.accepted_ending_id = offer.ending_id
    next_world.accepted_ending_offer_id = offer.offer_id
    next_world.accepted_ending_turn = next_world.turn_number
    next_world.final_summary = offer.final_summary or offer.summary
    _mark_event_decided(next_world, offer, accepted=True)
    _append_decision_timeline(next_world, offer, accepted=True)
    return EndingDecisionResult(
        world_state=next_world,
        offer_record=offer,
        accepted=True,
        summary=f"Accepted ending: {offer.title}\n\n{next_world.final_summary}",
    )


def reject_ending_offer(
    world_state: WorldStateV2,
    *,
    player_entity_id: str,
    offer_query: str = "latest",
) -> EndingDecisionResult:
    next_world = world_state.model_copy(deep=True)
    offer = _find_active_ending_offer(
        next_world,
        player_entity_id=player_entity_id,
        offer_query=offer_query,
    )
    if offer is None:
        return EndingDecisionResult(
            world_state=next_world,
            errors=[f"active ending offer not found: {offer_query}"],
        )
    delay = int(offer.metadata.get("reoffer_delay_turns", 3))
    reoffer_after_turn = next_world.turn_number + delay
    offer.status = EndingOfferStatus.REJECTED
    offer.rejected_turn = next_world.turn_number
    offer.reoffer_after_turn = reoffer_after_turn
    next_world.ending_reoffer_after_turns[offer.ending_id] = reoffer_after_turn
    _mark_event_decided(next_world, offer, accepted=False)
    _append_decision_timeline(next_world, offer, accepted=False)
    return EndingDecisionResult(
        world_state=next_world,
        offer_record=offer,
        rejected=True,
        summary=(
            f"Rejected ending: {offer.title}\n"
            f"The same ending cannot be offered again before turn {reoffer_after_turn}."
        ),
    )


def _ending_is_eligible(
    world_state: WorldStateV2,
    ending: ScenarioEndingDefinition,
) -> tuple[bool, str]:
    if not ending.enabled:
        return False, "disabled"
    turn = world_state.turn_number
    if turn < ending.min_turn:
        return False, f"turn {turn} before {ending.min_turn}"
    if ending.max_turn is not None and turn > ending.max_turn:
        return False, f"turn {turn} after {ending.max_turn}"
    reoffer_after = world_state.ending_reoffer_after_turns.get(ending.ending_id)
    if reoffer_after is not None and turn < reoffer_after:
        return False, f"reoffer delayed until turn {reoffer_after}"
    if any(
        offer.ending_id == ending.ending_id and offer.status == EndingOfferStatus.OFFERED
        for offer in world_state.ending_offers
    ):
        return False, "already offered"
    if not _metric_bounds_ok(
        world_state.truth_metrics,
        ending.truth_metric_minimums,
        ending.truth_metric_maximums,
    ):
        return False, "truth metric bounds failed"
    if not _metric_bounds_ok(
        world_state.public_metrics,
        ending.public_metric_minimums,
        ending.public_metric_maximums,
    ):
        return False, "public metric bounds failed"
    if not _metric_bounds_ok(
        world_state.hidden_clocks,
        ending.hidden_clock_minimums,
        ending.hidden_clock_maximums,
    ):
        return False, "hidden clock bounds failed"
    for commitment in ending.required_active_commitments:
        if commitment not in world_state.active_commitments:
            return False, f"missing commitment: {commitment}"
    event_ids = {record.event_id for record in world_state.event_history}
    ending_ids = {
        str(record.metadata["ending_id"])
        for record in world_state.event_history
        if record.metadata.get("ending_id")
    }
    recorded = event_ids | ending_ids
    for event_id in ending.required_event_ids:
        if event_id not in recorded:
            return False, f"missing event: {event_id}"
    for event_id in ending.excluded_event_ids:
        if event_id in recorded:
            return False, f"excluded event present: {event_id}"
    if not _has_condition(ending):
        return False, "no ending condition configured"
    return True, ""


def _build_offer(
    world_state: WorldStateV2,
    ending: ScenarioEndingDefinition,
    player_entity_id: str,
) -> EndingOfferRecord:
    offer_id = f"ending_{ending.ending_id}_{world_state.turn_number}_{len(world_state.ending_offers) + 1}"
    return EndingOfferRecord(
        offer_id=offer_id,
        ending_id=ending.ending_id,
        title=ending.title,
        summary=ending.summary,
        turn_number=world_state.turn_number,
        visible_to=list(ending.visible_to) or ([player_entity_id] if player_entity_id else []),
        final_summary=_build_final_summary(world_state, ending),
        metadata={"reoffer_delay_turns": ending.reoffer_delay_turns},
    )


def _build_event_record(
    world_state: WorldStateV2,
    ending: ScenarioEndingDefinition,
    offer: EndingOfferRecord,
) -> ScenarioEventRecord:
    return ScenarioEventRecord(
        event_id=offer.offer_id,
        title=ending.title,
        summary=ending.summary,
        kind="ending",
        turn_number=world_state.turn_number,
        urgency=ending.urgency,
        visible_to=list(offer.visible_to),
        related_entity_ids=ending.related_entity_ids,
        problem_title=f"Ending available: {ending.title}",
        problem_summary=(
            f"{ending.summary} Use ACCEPT ENDING to conclude, or REJECT ENDING "
            "to continue the crisis."
        ),
        public=bool(ending.public_timeline_title),
        metadata={
            "ending_id": ending.ending_id,
            "ending_offer_id": offer.offer_id,
            "reoffer_delay_turns": ending.reoffer_delay_turns,
        },
    )


def _append_ending_timelines(
    world_state: WorldStateV2,
    ending: ScenarioEndingDefinition,
    record: ScenarioEventRecord,
) -> None:
    world_state.omniscient_timeline.append(
        TimelineEntry(
            entry_id=f"omn_ending_{world_state.turn_number}_{ending.ending_id}",
            turn=world_state.turn_number,
            scope=TimelineScope.OMNISCIENT,
            title=ending.title,
            summary=ending.summary,
            source="ending_evaluator",
            tags=["scenario_event", "ending", ending.ending_id],
            created_at=_deterministic_time(world_state.turn_number),
            metadata={
                "event_id": record.event_id,
                "ending_id": ending.ending_id,
                "ending_offer_id": record.metadata["ending_offer_id"],
            },
        )
    )
    if ending.public_timeline_title:
        world_state.public_timeline.append(
            TimelineEntry(
                entry_id=f"public_ending_{world_state.turn_number}_{ending.ending_id}",
                turn=world_state.turn_number,
                scope=TimelineScope.PUBLIC,
                title=ending.public_timeline_title,
                summary=ending.public_timeline_summary or ending.summary,
                source="ending_evaluator",
                tags=["scenario_event", "public", "ending"],
                created_at=_deterministic_time(world_state.turn_number),
                metadata={
                    "event_id": record.event_id,
                    "ending_id": ending.ending_id,
                },
            )
        )


def _build_final_summary(
    world_state: WorldStateV2,
    ending: ScenarioEndingDefinition,
) -> str:
    parts = [ending.final_summary or ending.summary]
    public_entries = world_state.public_timeline.latest(2)
    if public_entries:
        parts.append(
            "Public timeline: "
            + " | ".join(f"{entry.title}: {entry.summary}" for entry in public_entries)
        )
    classified_entries = world_state.omniscient_timeline.latest(3)
    if classified_entries:
        parts.append(
            "Classified timeline: "
            + " | ".join(f"{entry.title}: {entry.summary}" for entry in classified_entries)
        )
    unresolved = _unresolved_issues(world_state)
    if unresolved:
        parts.append("Unresolved issues: " + "; ".join(unresolved[:5]))
    if world_state.active_commitments:
        parts.append("Active commitments: " + ", ".join(sorted(world_state.active_commitments)))
    return "\n".join(parts)


def _unresolved_issues(world_state: WorldStateV2) -> list[str]:
    issues: list[str] = []
    if float(world_state.truth_metrics.get("missile_operational_progress", 0.0)) >= 0.45:
        issues.append("missile readiness remains contested")
    if float(world_state.truth_metrics.get("cuban_invasion_fear", 0.0)) >= 0.6:
        issues.append("Cuban invasion fear remains high")
    if float(world_state.hidden_clocks.get("nuclear_escalation", 0.0)) >= 0.55:
        issues.append("nuclear escalation risk remains elevated")
    if float(world_state.hidden_clocks.get("command_and_control_risk", 0.0)) >= 0.55:
        issues.append("local command control remains unstable")
    if float(world_state.public_metrics.get("public_alarm", 0.0)) >= 0.6:
        issues.append("public alarm remains elevated")
    if world_state.pending_actions:
        issues.append("delayed actions are still in motion")
    if any(choice.active_for(world_state.turn_number) for choice in world_state.pending_event_choices):
        issues.append("event choices were unresolved")
    return issues


def _active_ending_offer(
    world_state: WorldStateV2,
    player_entity_id: str,
) -> EndingOfferRecord | None:
    offers = active_ending_offers(world_state, player_entity_id=player_entity_id)
    return offers[-1] if offers else None


def _find_active_ending_offer(
    world_state: WorldStateV2,
    *,
    player_entity_id: str,
    offer_query: str,
) -> EndingOfferRecord | None:
    query = offer_query.strip().lower() or "latest"
    offers = active_ending_offers(world_state, player_entity_id=player_entity_id)
    for offer in offers:
        if offer.offer_id.lower() == query or offer.ending_id.lower() == query:
            return offer
    for offer in offers:
        if (
            offer.offer_id.lower().startswith(query)
            or offer.ending_id.lower().startswith(query)
            or offer.title.lower().startswith(query)
        ):
            return offer
    return offers[-1] if query in {"latest", "current", "ending"} and offers else None


def _mark_event_decided(
    world_state: WorldStateV2,
    offer: EndingOfferRecord,
    *,
    accepted: bool,
) -> None:
    for record in world_state.event_history:
        if record.metadata.get("ending_offer_id") != offer.offer_id:
            continue
        record.metadata["ending_decision"] = "accepted" if accepted else "rejected"
        if not accepted:
            record.status = ScenarioEventStatus.EXPIRED


def _append_decision_timeline(
    world_state: WorldStateV2,
    offer: EndingOfferRecord,
    *,
    accepted: bool,
) -> None:
    title = "Ending Accepted" if accepted else "Ending Rejected"
    summary = (
        f"{offer.title} was accepted as the crisis endpoint."
        if accepted
        else (
            f"{offer.title} was rejected; it cannot be offered again before "
            f"turn {offer.reoffer_after_turn}."
        )
    )
    world_state.omniscient_timeline.append(
        TimelineEntry(
            entry_id=f"omn_ending_decision_{world_state.turn_number}_{offer.offer_id}",
            turn=world_state.turn_number,
            scope=TimelineScope.OMNISCIENT,
            title=title,
            summary=summary,
            source="ending_evaluator",
            tags=["ending", "accepted" if accepted else "rejected", offer.ending_id],
            created_at=_deterministic_time(world_state.turn_number),
            metadata={
                "ending_id": offer.ending_id,
                "ending_offer_id": offer.offer_id,
            },
        )
    )


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


def _has_condition(ending: ScenarioEndingDefinition) -> bool:
    return bool(
        ending.min_turn > 1
        or ending.max_turn is not None
        or ending.truth_metric_minimums
        or ending.truth_metric_maximums
        or ending.public_metric_minimums
        or ending.public_metric_maximums
        or ending.hidden_clock_minimums
        or ending.hidden_clock_maximums
        or ending.required_active_commitments
        or ending.required_event_ids
        or ending.excluded_event_ids
    )


def _deterministic_time(turn_number: int) -> datetime:
    return datetime.fromtimestamp(turn_number, tz=timezone.utc)
