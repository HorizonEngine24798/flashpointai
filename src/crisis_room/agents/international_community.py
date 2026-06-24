from __future__ import annotations

from crisis_room.agents.base import AgentOutput
from crisis_room.agents.context import build_task_request, build_visible_context
from crisis_room.agents.signal_builders import signal_from_candidate
from crisis_room.llm.contracts import LLMClient
from crisis_room.llm.task_contracts import InternationalPressure
from crisis_room.state.world import EntityState, WorldStateV2


class InternationalCommunityAgent:
    """Ambient legitimacy, media, institutional, and diplomatic pressure actor."""

    def __init__(self, entity_id: str = "international") -> None:
        self.entity_id = entity_id

    def run_turn(
        self,
        entity_state: EntityState,
        world_state: WorldStateV2,
        llm_client: LLMClient,
    ) -> AgentOutput:
        visible_context = build_visible_context(entity_state, world_state)
        request = build_task_request(
            label=f"international.{entity_state.entity_id}.pressure",
            system_prompt=(
                "You are the international community pressure model: institutions, "
                "non-aligned governments, media, markets, humanitarian groups, and "
                "external legitimacy. Use only visible context."
            ),
            visible_context=visible_context,
            task_instruction=(
                "Produce the external pressure response for this turn. Pressure "
                "signals should be public or plausibly diplomatic information "
                "packets, not direct mutations of game state. Separate legitimacy "
                "concerns from requested restraints, and target signals only at "
                "visible entity ids when a specific recipient is needed."
            ),
            response_schema_name="InternationalPressure",
            metadata={
                "agent": self.entity_id,
                "entity_id": entity_state.entity_id,
                "turn_number": world_state.turn_number,
            },
            max_tokens=1300,
        )
        pressure = llm_client.complete_json(request, InternationalPressure)
        known_entity_ids = set(world_state.actors)
        emitted_signals = [
            signal_from_candidate(
                candidate,
                source_entity_id=entity_state.entity_id,
                turn_number=world_state.turn_number,
                suffix=f"pressure_{index}",
                known_entity_ids=known_entity_ids,
                metadata={"task": "international_pressure"},
            )
            for index, candidate in enumerate(pressure.pressure_signals, start=1)
        ]
        return AgentOutput(
            entity_id=entity_state.entity_id,
            perception_summary=pressure.situation_summary,
            internal_debate=pressure.legitimacy_concerns + pressure.requested_restraints,
            emitted_signals=emitted_signals,
            raw_llm_outputs=[
                {"task": "international_pressure", "response": pressure.model_dump(mode="json")}
            ],
        )
