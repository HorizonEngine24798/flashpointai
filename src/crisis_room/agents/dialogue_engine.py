from __future__ import annotations

from crisis_room.agents.context import build_task_request, build_visible_context
from crisis_room.config.gameplay import DIALOGUE_MAX_TOKENS
from crisis_room.engine.actions import ActionDefinition, ScenarioCapability
from crisis_room.llm.contracts import ChatRole, LLMClient, LLMMessage, LLMRequest
from crisis_room.llm.diagnostics import LlamaCppJSONError
from crisis_room.llm.prompts import (
    ADVISOR_JSON_RETRY_INSTRUCTION,
    ADVISOR_SYSTEM,
    ADVISOR_TASK,
)
from crisis_room.llm.task_contracts import AdvisorCouncilResponse
from crisis_room.state.world import WorldStateV2


class DialogueEngineAgent:
    """Player-facing advisor layer grounded in player-visible information."""

    def __init__(
        self,
        *,
        entity_id: str = "dialogue_engine",
        action_catalog: list[ActionDefinition] | None = None,
        capabilities: list[ScenarioCapability] | None = None,
    ) -> None:
        self.entity_id = entity_id
        self.action_catalog = action_catalog or []
        self.capabilities = capabilities or []

    def respond_to_player(
        self,
        world_state: WorldStateV2,
        *,
        player_entity_id: str,
        player_message: str,
        llm_client: LLMClient,
        json_retries: int = 0,
    ) -> AdvisorCouncilResponse:
        player_state = world_state.require_entity(player_entity_id)
        visible_context = build_visible_context(
            player_state,
            world_state,
            action_catalog=self.action_catalog,
            capabilities=self.capabilities,
            player_message=player_message,
            extra={"dialogue_engine_id": self.entity_id},
        )
        request = build_task_request(
            label=f"dialogue.{player_entity_id}.advisor_response",
            system_prompt=ADVISOR_SYSTEM,
            visible_context=visible_context,
            task_instruction=ADVISOR_TASK,
            response_schema_name="AdvisorCouncilResponse",
            metadata={
                "agent": self.entity_id,
                "player_entity_id": player_entity_id,
                "turn_number": world_state.turn_number,
            },
            max_tokens=DIALOGUE_MAX_TOKENS,
        )
        for attempt in range(json_retries + 1):
            attempt_request = request if attempt == 0 else _retry_request(request)
            try:
                response = llm_client.complete_json(attempt_request, AdvisorCouncilResponse)
                return _validated_council_response(
                    response,
                    world_state,
                    player_entity_id=player_entity_id,
                    capabilities=self.capabilities,
                    action_catalog=self.action_catalog,
                )
            except LlamaCppJSONError:
                if attempt >= json_retries:
                    raise
        raise RuntimeError("unreachable advisor retry state")

    def answer(
        self,
        world_state: WorldStateV2,
        *,
        player_entity_id: str,
        player_message: str,
        llm_client: LLMClient,
        json_retries: int = 0,
    ) -> AdvisorCouncilResponse:
        return self.respond_to_player(
            world_state,
            player_entity_id=player_entity_id,
            player_message=player_message,
            llm_client=llm_client,
            json_retries=json_retries,
        )


def _retry_request(request: LLMRequest) -> LLMRequest:
    messages = [message.model_copy() for message in request.messages]
    for index in range(len(messages) - 1, -1, -1):
        if messages[index].role == ChatRole.USER:
            messages[index].content = (
                f"{messages[index].content}\n\n{ADVISOR_JSON_RETRY_INSTRUCTION}"
            )
            break
    else:
        messages.append(
            LLMMessage(role=ChatRole.USER, content=ADVISOR_JSON_RETRY_INSTRUCTION)
        )
    return request.model_copy(update={"messages": messages})


def _validated_council_response(
    response: AdvisorCouncilResponse,
    world_state: WorldStateV2,
    *,
    player_entity_id: str,
    capabilities: list[ScenarioCapability],
    action_catalog: list[ActionDefinition],
) -> AdvisorCouncilResponse:
    council = world_state.advisor_councils.get(player_entity_id)
    if council is None:
        return response

    allowed_advisor_ids = set(council.advisors)
    seen_view_ids: set[str] = set()
    canonical_views = []
    for view in response.advisor_views:
        if view.advisor_id not in allowed_advisor_ids:
            raise ValueError(f"advisor response referenced unknown advisor_id: {view.advisor_id}")
        if view.advisor_id in seen_view_ids:
            raise ValueError(f"advisor response repeated advisor_id: {view.advisor_id}")
        seen_view_ids.add(view.advisor_id)
        advisor = council.advisors[view.advisor_id]
        canonical_views.append(view.model_copy(update={"advisor_name": advisor.name}))

    for delta in response.proposed_advisor_deltas:
        if delta.advisor_id not in allowed_advisor_ids:
            raise ValueError(
                f"advisor response proposed delta for unknown advisor_id: {delta.advisor_id}"
            )

    known_capabilities = {capability.capability_id for capability in capabilities}
    unknown_capabilities = [
        capability_id
        for capability_id in response.suggested_capability_ids
        if capability_id not in known_capabilities
    ]
    if unknown_capabilities:
        raise ValueError(
            "advisor response suggested unknown capability_id: "
            + ", ".join(unknown_capabilities)
        )

    known_actions = {definition.action_id for definition in action_catalog}
    unknown_actions = [
        action_id
        for action_id in response.suggested_action_ids
        if action_id not in known_actions
    ]
    if unknown_actions:
        raise ValueError(
            "advisor response suggested unknown action_id: " + ", ".join(unknown_actions)
        )

    return response.model_copy(update={"advisor_views": canonical_views})
