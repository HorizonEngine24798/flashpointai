from __future__ import annotations

from crisis_room.engine.actions import ActionPackage
from crisis_room.llm.task_contracts import BackchannelCounterpartResponse
from crisis_room.scenario.cuba import CUBA_DIRECT_KREMLIN_MESSAGE_CAPABILITY_ID
from crisis_room.state.backchannels import BackchannelThread
from crisis_room.state.signals import SignalChannel
from crisis_room.state.world import WorldStateV2


_FORMAL_BACKCHANNEL_PREFIXES = ("formal:", "action:", "commit:")
_FORMAL_BACKCHANNEL_TOKENS = [
    "air strike",
    "bomb",
    "deal",
    "guarantee",
    "invasion",
    "jupiter",
    "missile trade",
    "non invasion",
    "non-invasion",
    "pledge",
    "quarantine",
    "remove missiles",
    "reciprocal",
    "settlement",
    "strike",
    "trade",
    "turkey",
    "ultimatum",
    "withdraw",
    "withdrawal",
]


def _is_formal_backchannel_message(message_text: str) -> bool:
    lowered = message_text.strip().lower()
    if any(lowered.startswith(prefix) for prefix in _FORMAL_BACKCHANNEL_PREFIXES):
        return True
    return any(token in lowered for token in _FORMAL_BACKCHANNEL_TOKENS)


def _formal_backchannel_action_package(
    world_state: WorldStateV2,
    *,
    player_entity_id: str,
    target_entity_id: str,
    message_text: str,
    thread: BackchannelThread,
    counterpart_response: BackchannelCounterpartResponse,
) -> ActionPackage:
    clean_message = _strip_formal_prefix(message_text)
    return ActionPackage(
        actor_id=player_entity_id,
        action_id="backchannel_message",
        capability_id=CUBA_DIRECT_KREMLIN_MESSAGE_CAPABILITY_ID,
        target_ids=[target_entity_id],
        channel=SignalChannel.BACKCHANNEL,
        intent_summary=clean_message,
        private_rationale=clean_message,
        submitted_turn=world_state.turn_number,
        commitment_level=0.55,
        metadata={
            "created_by": "prepare_backchannel_message",
            "direct_backchannel_message": True,
            "formal_backchannel_message": True,
            "backchannel_thread_id": thread.thread_id,
            "counterpart_response_text": counterpart_response.response_text,
            "counterpart_trust_delta": counterpart_response.trust_delta,
            "counterpart_leak_risk_delta": counterpart_response.leak_risk_delta,
            "counterpart_relationship_delta": counterpart_response.relationship_delta,
            "leak_summary": _direct_message_leak_summary(player_entity_id, target_entity_id),
        },
        parameters={"message_text": clean_message},
    )


def _strip_formal_prefix(message_text: str) -> str:
    stripped = message_text.strip()
    lowered = stripped.lower()
    for prefix in _FORMAL_BACKCHANNEL_PREFIXES:
        if lowered.startswith(prefix):
            return stripped[len(prefix) :].strip()
    return stripped


def _direct_message_leak_summary(player_entity_id: str, target_entity_id: str) -> str:
    return (
        "Rumor spreads that a direct backchannel message moved between "
        f"{player_entity_id} and {target_entity_id}."
    )

