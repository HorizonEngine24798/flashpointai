from __future__ import annotations

from crisis_room.agents.context import build_task_request, build_visible_context
from crisis_room.engine.actions import ActionDefinition, ScenarioCapability
from crisis_room.llm.contracts import LLMClient
from crisis_room.llm.prompts import (
    BACKCHANNEL_COUNTERPART_SYSTEM,
    BACKCHANNEL_COUNTERPART_TASK,
    BACKCHANNEL_STATE_SYSTEM,
    BACKCHANNEL_STATE_TASK,
)
from crisis_room.llm.task_contracts import (
    BackchannelCounterpartResponse,
    BackchannelStateChange,
)
from crisis_room.state.backchannels import BackchannelThread
from crisis_room.state.world import WorldStateV2


def _request_counterpart_response(
    world_state: WorldStateV2,
    *,
    player_entity_id: str,
    target_entity_id: str,
    message_text: str,
    thread: BackchannelThread,
    action_catalog: list[ActionDefinition],
    capabilities: list[ScenarioCapability],
    llm_client: LLMClient,
) -> BackchannelCounterpartResponse:
    target = world_state.actors[target_entity_id]
    visible_context = build_visible_context(
        target,
        world_state,
        action_catalog=action_catalog,
        capabilities=capabilities,
        player_message=message_text,
        extra={
            "incoming_backchannel_message": {
                "from_entity_id": player_entity_id,
                "to_entity_id": target_entity_id,
                "thread_id": thread.thread_id,
                "trust_level": thread.trust_level,
                "leak_risk": thread.leak_risk,
                "player_messages_remaining": thread.player_messages_remaining_for_turn(
                    world_state.turn_number
                ),
            }
        },
    )
    request = build_task_request(
        label=f"backchannel.{target_entity_id}.counterpart_response",
        system_prompt=BACKCHANNEL_COUNTERPART_SYSTEM,
        visible_context=visible_context,
        task_instruction=BACKCHANNEL_COUNTERPART_TASK,
        response_schema_name="BackchannelCounterpartResponse",
        metadata={
            "agent": "backchannel_counterpart",
            "actor_id": target_entity_id,
            "player_entity_id": player_entity_id,
            "turn_number": world_state.turn_number,
        },
        max_tokens=700,
    )
    return llm_client.complete_json(request, BackchannelCounterpartResponse)


def _request_backchannel_state_change(
    world_state: WorldStateV2,
    *,
    player_entity_id: str,
    target_entity_id: str,
    message_text: str,
    response: BackchannelCounterpartResponse,
    thread: BackchannelThread,
    action_catalog: list[ActionDefinition],
    capabilities: list[ScenarioCapability],
    llm_client: LLMClient,
) -> BackchannelStateChange:
    target = world_state.actors[target_entity_id]
    visible_context = build_visible_context(
        target,
        world_state,
        action_catalog=action_catalog,
        capabilities=capabilities,
        player_message=message_text,
        extra={
            "completed_backchannel_exchange": {
                "from_entity_id": player_entity_id,
                "to_entity_id": target_entity_id,
                "thread_id": thread.thread_id,
                "target_response": response.model_dump(mode="json"),
                "trust_level": thread.trust_level,
                "leak_risk": thread.leak_risk,
            }
        },
    )
    request = build_task_request(
        label=f"backchannel.{target_entity_id}.state_change",
        system_prompt=BACKCHANNEL_STATE_SYSTEM,
        visible_context=visible_context,
        task_instruction=BACKCHANNEL_STATE_TASK,
        response_schema_name="BackchannelStateChange",
        metadata={
            "agent": "backchannel_state_change",
            "actor_id": target_entity_id,
            "player_entity_id": player_entity_id,
            "turn_number": world_state.turn_number,
        },
        max_tokens=700,
    )
    return llm_client.complete_json(request, BackchannelStateChange)

