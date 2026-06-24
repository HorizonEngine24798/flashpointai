from __future__ import annotations

from crisis_room.agents.context import build_task_request, build_visible_context
from crisis_room.engine.actions import ActionDefinition
from crisis_room.llm.contracts import LLMClient
from crisis_room.llm.task_contracts import AdvisorResponse
from crisis_room.state.world import WorldStateV2


class DialogueEngineAgent:
    """Player-facing advisor layer grounded in player-visible information."""

    def __init__(
        self,
        *,
        entity_id: str = "dialogue_engine",
        action_catalog: list[ActionDefinition] | None = None,
    ) -> None:
        self.entity_id = entity_id
        self.action_catalog = action_catalog or []

    def respond_to_player(
        self,
        world_state: WorldStateV2,
        *,
        player_entity_id: str,
        player_message: str,
        llm_client: LLMClient,
    ) -> AdvisorResponse:
        player_state = world_state.require_entity(player_entity_id)
        visible_context = build_visible_context(
            player_state,
            world_state,
            action_catalog=self.action_catalog,
            player_message=player_message,
            extra={"dialogue_engine_id": self.entity_id},
        )
        request = build_task_request(
            label=f"dialogue.{player_entity_id}.advisor_response",
            system_prompt=(
                "You are the crisis room dialogue engine. Simulate multiple "
                "advisor perspectives for the player, using only the provided "
                "visible context. Be candid about uncertainty and tradeoffs."
            ),
            visible_context=visible_context,
            task_instruction=(
                "Answer the player's message as contested crisis-room advice. "
                "Use advisor_views for distinct viewpoints, risk_warnings for "
                "concrete hazards, suggested_action_ids only for actions listed "
                "in the visible action catalog, and visible_context_limits for "
                "important things the player may not know. Do not imply access "
                "to hidden clocks, truth metrics, or private rival state unless "
                "that information appears in the visible context."
            ),
            response_schema_name="AdvisorResponse",
            metadata={
                "agent": self.entity_id,
                "player_entity_id": player_entity_id,
                "turn_number": world_state.turn_number,
            },
            max_tokens=1400,
        )
        return llm_client.complete_json(request, AdvisorResponse)

    def answer(
        self,
        world_state: WorldStateV2,
        *,
        player_entity_id: str,
        player_message: str,
        llm_client: LLMClient,
    ) -> AdvisorResponse:
        return self.respond_to_player(
            world_state,
            player_entity_id=player_entity_id,
            player_message=player_message,
            llm_client=llm_client,
        )
