from __future__ import annotations

from crisis_room.agents.base import AgentOutput
from crisis_room.agents.context import build_task_request
from crisis_room.config.gameplay import (
    EVENT_CREATOR_MAX_TOKENS,
    VISIBLE_CONTEXT_SCENARIO_NOTES_LIMIT,
    VISIBLE_CONTEXT_TIMELINE_LIMIT,
)
from crisis_room.llm.contracts import LLMClient
from crisis_room.llm.task_contracts import EventCreatorResponse, PublicBrief
from crisis_room.scenario.events import ScenarioEventDefinition
from crisis_room.state.timelines import TimelineEntry, TimelineScope
from crisis_room.state.world import WorldStateV2


class EventCreatorAgent:
    """Media desk and crisis pressure source that proposes optional event candidates."""

    def __init__(self, entity_id: str = "event_creator") -> None:
        self.entity_id = entity_id

    def create_candidate(
        self,
        world_state: WorldStateV2,
        *,
        llm_client: LLMClient,
        scenario_notes: list[str] | None = None,
        scenario_events: list[ScenarioEventDefinition] | None = None,
    ) -> AgentOutput:
        notes = scenario_notes or []
        bounded_notes = notes[:VISIBLE_CONTEXT_SCENARIO_NOTES_LIMIT]
        public_events = _scenario_public_event_context(
            scenario_events or [],
            limit=VISIBLE_CONTEXT_SCENARIO_NOTES_LIMIT,
        )
        public_entries = world_state.public_timeline.latest(VISIBLE_CONTEXT_TIMELINE_LIMIT)
        visible_context = {
            "scenario_id": world_state.scenario_id,
            "turn_number": world_state.turn_number,
            "time_label": world_state.time_label,
            "public_metrics": world_state.public_metrics,
            "public_timeline": [
                entry.model_dump(mode="json")
                for entry in public_entries
            ],
            "actor_public_profiles": [
                {
                    "entity_id": entity.entity_id,
                    "name": entity.name,
                    "entity_type": entity.entity_type.value,
                    "role": entity.role,
                    "public_goals": entity.public_goals,
                }
                for entity in world_state.actors.values()
            ],
            "scenario_notes": bounded_notes,
            "scenario_public_events": public_events,
            "context_limits": {
                "public_timeline_limit": VISIBLE_CONTEXT_TIMELINE_LIMIT,
                "public_timeline_total": len(world_state.public_timeline.entries),
                "public_timeline_truncated": len(public_entries)
                < len(world_state.public_timeline.entries),
                "scenario_notes_limit": VISIBLE_CONTEXT_SCENARIO_NOTES_LIMIT,
                "scenario_notes_total": len(notes),
                "scenario_notes_truncated": len(bounded_notes) < len(notes),
                "scenario_public_event_limit": VISIBLE_CONTEXT_SCENARIO_NOTES_LIMIT,
                "scenario_public_event_total": len(scenario_events or []),
                "scenario_public_event_truncated": len(public_events)
                < len(scenario_events or []),
            },
        }
        request = build_task_request(
            label=f"event_creator.{self.entity_id}.media_event_turn",
            system_prompt=(
                "You are the media desk and event creator for a political-military "
                "crisis. Every turn, write a public-facing headline brief from "
                "visible information and, only if warranted, propose one major "
                "historical, chaotic, institutional, local-initiative, or media "
                "pressure event. Do not mutate clocks, timelines, or resources."
            ),
            visible_context=visible_context,
            task_instruction=(
                "Return an EventCreatorResponse. Always fill public_brief as headline "
                "news using only public timeline, public metrics, actor public "
                "profiles, scenario notes, and scenario_public_events. Keep omitted "
                "private topics explicit when the media cannot know something. "
                "Set event_candidate only when a major event is relevant this turn; "
                "otherwise return null and use editorial_notes to explain why the "
                "headline is enough. If you propose an event, include suggested_signals "
                "for information that should enter the info channel. Use "
                "deterministic_effect_hints only as non-authoritative hints."
            ),
            response_schema_name="EventCreatorResponse",
            metadata={"agent": self.entity_id, "turn_number": world_state.turn_number},
            max_tokens=EVENT_CREATOR_MAX_TOKENS,
        )
        response = llm_client.complete_json(request, EventCreatorResponse)
        candidate = response.event_candidate
        public_entry = _public_brief_entry(world_state, response.public_brief)
        summary = f"{response.public_brief.headline}: {response.public_brief.summary}"
        if candidate is not None:
            summary = f"{summary} Major event candidate: {candidate.title}: {candidate.summary}"
        raw_outputs: list[dict[str, object]] = [
            {"task": "event_creator_response", "response": response.model_dump(mode="json")},
            {"task": "public_brief", "response": response.public_brief.model_dump(mode="json")},
        ]
        if candidate is not None:
            raw_outputs.append(
                {"task": "event_candidate", "response": candidate.model_dump(mode="json")}
            )
        return AgentOutput(
            entity_id=self.entity_id,
            perception_summary=summary,
            internal_debate=list(response.editorial_notes),
            public_timeline_delta=[public_entry],
            raw_llm_outputs=raw_outputs,
        )


def _scenario_public_event_context(
    scenario_events: list[ScenarioEventDefinition],
    *,
    limit: int,
) -> list[dict[str, object]]:
    context: list[dict[str, object]] = []
    for event in scenario_events[: max(limit, 0)]:
        if not event.enabled:
            continue
        context.append(
            {
                "event_id": event.event_id,
                "title": event.title,
                "summary": event.summary,
                "kind": event.kind,
                "problem_title": event.problem_title,
                "problem_summary": event.problem_summary,
                "urgency": event.urgency,
                "related_entity_ids": event.related_entity_ids,
                "related_action_ids": event.related_action_ids,
                "public_timeline_title": event.public_timeline_title,
                "public_timeline_summary": event.public_timeline_summary,
            }
        )
    return context


def _public_brief_entry(world_state: WorldStateV2, brief: PublicBrief) -> TimelineEntry:
    return TimelineEntry(
        turn=world_state.turn_number,
        scope=TimelineScope.PUBLIC,
        title=brief.headline,
        summary=brief.summary,
        source="event_creator",
        tags=["media", "headline"],
        metadata={"public_risk_read": brief.public_risk_read},
    )
