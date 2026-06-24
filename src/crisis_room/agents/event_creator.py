from __future__ import annotations

from crisis_room.agents.base import AgentOutput
from crisis_room.agents.context import build_task_request
from crisis_room.agents.signal_builders import signal_from_candidate
from crisis_room.llm.contracts import LLMClient
from crisis_room.llm.task_contracts import EventCandidate, SignalCandidate
from crisis_room.state.signals import PayloadType, SignalChannel, SignalVisibility
from crisis_room.state.world import WorldStateV2


class EventCreatorAgent:
    """Historical gravity and chaos pressure source that proposes event candidates."""

    def __init__(self, entity_id: str = "event_creator") -> None:
        self.entity_id = entity_id

    def create_candidate(
        self,
        world_state: WorldStateV2,
        *,
        llm_client: LLMClient,
        scenario_notes: list[str] | None = None,
    ) -> AgentOutput:
        visible_context = {
            "scenario_id": world_state.scenario_id,
            "turn_number": world_state.turn_number,
            "time_label": world_state.time_label,
            "public_metrics": world_state.public_metrics,
            "public_timeline": [
                entry.model_dump(mode="json")
                for entry in world_state.public_timeline.latest(8)
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
            "scenario_notes": scenario_notes or [],
            "context_limits": {
                "public_timeline_limit": 8,
                "scenario_notes_total": len(scenario_notes or []),
            },
        }
        request = build_task_request(
            label=f"event_creator.{self.entity_id}.candidate",
            system_prompt=(
                "You are the event creator for a political-military crisis. "
                "Propose historically grounded or chaotic pressure events from "
                "publicly visible state; do not mutate clocks, timelines, or resources."
            ),
            visible_context=visible_context,
            task_instruction=(
                "Return one plausible event candidate for this turn. Include "
                "suggested_signals for information that should enter the info channel. "
                "Use deterministic_effect_hints only as non-authoritative hints. "
                "Prefer pressure that follows from public timeline, public metrics, "
                "actor profiles, or scenario notes rather than private state."
            ),
            response_schema_name="EventCandidate",
            metadata={"agent": self.entity_id, "turn_number": world_state.turn_number},
            max_tokens=1300,
        )
        candidate = llm_client.complete_json(request, EventCandidate)
        signal_candidates = candidate.suggested_signals or [
            SignalCandidate(
                channel=SignalChannel.GAMEMASTER,
                payload_type=PayloadType.EVENT_NOTICE,
                content=f"{candidate.title}: {candidate.summary}",
                visibility=SignalVisibility.PUBLIC,
                reliability=candidate.plausibility,
                urgency=candidate.escalation_pressure,
            )
        ]
        emitted_signals = [
            signal_from_candidate(
                signal_candidate,
                source_entity_id=self.entity_id,
                turn_number=world_state.turn_number,
                suffix=f"{candidate.candidate_id}_{index}",
                known_entity_ids=set(world_state.actors),
                metadata={
                    "task": "event_candidate",
                    "candidate_id": candidate.candidate_id,
                    "event_kind": candidate.kind.value,
                },
            )
            for index, signal_candidate in enumerate(signal_candidates, start=1)
        ]
        return AgentOutput(
            entity_id=self.entity_id,
            perception_summary=f"{candidate.title}: {candidate.summary}",
            internal_debate=[candidate.reason_to_include] if candidate.reason_to_include else [],
            emitted_signals=emitted_signals,
            raw_llm_outputs=[
                {"task": "event_candidate", "response": candidate.model_dump(mode="json")}
            ],
        )
