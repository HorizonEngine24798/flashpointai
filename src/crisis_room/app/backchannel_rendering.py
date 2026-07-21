from __future__ import annotations

from typing import Any

from crisis_room.state.backchannels import BackchannelThreadStatus
from crisis_room.state.world import WorldStateV2


def render_backchannel_threads(world_state: WorldStateV2, *, viewer_entity_id: str) -> str:
    lines = ["BACKCHANNELS"]
    threads = [
        thread
        for thread in world_state.backchannel_threads.values()
        if viewer_entity_id in thread.participant_entity_ids
        and thread.status == BackchannelThreadStatus.OPEN
        and thread.expires_turn >= world_state.turn_number
    ]
    threads.sort(key=lambda thread: (thread.expires_turn, thread.last_active_turn))
    if not threads:
        lines.append("No active backchannel threads.")
        return "\n".join(lines)
    for thread in threads:
        counterpart_ids = [
            entity_id
            for entity_id in thread.participant_entity_ids
            if entity_id != viewer_entity_id
        ]
        counterpart = ", ".join(counterpart_ids) or "unknown counterpart"
        opened_by = _thread_opened_by(world_state, thread, viewer_entity_id)
        lines.append(
            f"- {counterpart}: opened by {opened_by}, open through turn {thread.expires_turn}, "
            f"trust {thread.trust_level:.0%}, leak risk {thread.leak_risk:.0%}"
        )
        if thread.player_entity_id == viewer_entity_id:
            lines.append(
                "  direct messages remaining: "
                f"{thread.player_messages_remaining_for_turn(world_state.turn_number)}"
            )
        if thread.message_records:
            latest = thread.message_records[-1]
            lines.append(f"  latest reported exchange: {latest.summary}")
    return "\n".join(lines)


def render_backchannel_direct_message_result(
    result: Any,
) -> str:
    if not result.accepted:
        lines = ["BACKCHANNEL FAILED"]
        lines.extend(f"- {error}" for error in result.errors)
        return "\n".join(lines)
    thread = result.world_state.backchannel_threads.get(result.thread_id)
    lines = [
        "BACKCHANNEL",
        f"Sent to {result.target_entity_id}: {result.player_message}",
        f"Reported response: {result.response_text}",
    ]
    if thread is not None:
        lines.append(
            f"Thread: {thread.player_messages_used}/{thread.max_player_messages} "
            f"direct messages used, open through turn {thread.expires_turn}."
        )
    return "\n".join(lines)


def _thread_opened_by(
    world_state: WorldStateV2,
    thread: object,
    viewer_entity_id: str,
) -> str:
    sender = str(getattr(thread, "metadata", {}).get("opened_by") or "")
    records = getattr(thread, "message_records", [])
    if not sender and records:
        sender = records[0].sender_entity_id
    if sender == viewer_entity_id:
        return "you"
    actor = world_state.actors.get(sender)
    return actor.name if actor is not None else (sender or "an unclear source")

