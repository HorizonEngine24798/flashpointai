from __future__ import annotations

from pydantic import BaseModel, Field

from crisis_room.agents.info_channel import PrototypeInfoChannel, RoutingResult
from crisis_room.engine.actions import ActionDefinition, ActionPackage
from crisis_room.engine.adjudication import DeterministicTurnResult
from crisis_room.engine.clocks import clamp
from crisis_room.state.backchannels import (
    BackchannelMessageRecord,
    BackchannelThread,
    BackchannelThreadStatus,
    BackchannelThreadUpdate,
)
from crisis_room.state.signals import PayloadType, Signal, SignalChannel, SignalVisibility
from crisis_room.state.world import WorldStateV2


DEFAULT_THREAD_LIFETIME_TURNS = 3
MAX_THREAD_RECORDS = 12
MAX_BACKCHANNEL_UPDATE_HISTORY = 30


class BackchannelDirectMessageResult(BaseModel):
    world_state: WorldStateV2
    accepted: bool
    errors: list[str] = Field(default_factory=list)
    target_entity_id: str = ""
    thread_id: str = ""
    player_message: str = ""
    response_text: str = ""
    routing_result: RoutingResult | None = None
    update: BackchannelThreadUpdate | None = None


def backchannel_thread_id(entity_a_id: str, entity_b_id: str) -> str:
    first, second = sorted([entity_a_id, entity_b_id])
    return f"backchannel:{first}:{second}"


def resolve_backchannel_target(
    world_state: WorldStateV2,
    *,
    player_entity_id: str,
    target_query: str,
) -> str | None:
    query = _normalize_target_query(target_query)
    if not query:
        return None
    if target_query in world_state.actors and target_query != player_entity_id:
        return target_query
    matches: list[str] = []
    for entity in world_state.actors.values():
        if entity.entity_id == player_entity_id:
            continue
        candidates = {
            _normalize_target_query(entity.entity_id),
            _normalize_target_query(entity.name),
            _normalize_target_query(entity.name.split()[0]),
        }
        if query in candidates or any(candidate.startswith(query) for candidate in candidates):
            matches.append(entity.entity_id)
    if len(matches) == 1:
        return matches[0]
    return None


def send_backchannel_message(
    world_state: WorldStateV2,
    *,
    player_entity_id: str,
    target_entity_id: str,
    message_text: str,
    info_channel: PrototypeInfoChannel | None = None,
) -> BackchannelDirectMessageResult:
    """Send one scarce direct message through an existing open thread."""

    next_world = world_state.model_copy(deep=True)
    update = BackchannelThreadUpdate(turn_number=next_world.turn_number)
    _expire_stale_threads(next_world, update)

    errors = _validate_direct_message(
        next_world,
        player_entity_id=player_entity_id,
        target_entity_id=target_entity_id,
        message_text=message_text,
    )
    thread_id = backchannel_thread_id(player_entity_id, target_entity_id)
    thread = next_world.backchannel_threads.get(thread_id)
    if not errors and thread is None:
        errors.append(f"no active backchannel thread with {target_entity_id}")
    if (
        not errors
        and thread is not None
        and thread.status != BackchannelThreadStatus.OPEN
    ):
        errors.append(f"backchannel thread with {target_entity_id} is not open")
    if (
        not errors
        and thread is not None
        and thread.expires_turn < next_world.turn_number
    ):
        thread.status = BackchannelThreadStatus.EXPIRED
        _append_unique(update.expired_thread_ids, thread.thread_id)
        _append_unique(update.summary, f"Backchannel expired: {thread.thread_id}.")
        errors.append(f"backchannel thread with {target_entity_id} has expired")
    if (
        not errors
        and thread is not None
        and thread.player_messages_remaining <= 0
    ):
        errors.append(f"direct message budget is exhausted for {target_entity_id}")

    if errors:
        persisted_update = _persist_backchannel_update(next_world, update)
        return BackchannelDirectMessageResult(
            world_state=next_world,
            accepted=False,
            errors=errors,
            target_entity_id=target_entity_id,
            thread_id=thread_id,
            player_message=message_text,
            update=persisted_update,
        )

    assert thread is not None
    message_effect = _direct_message_effect(message_text, thread)
    thread.player_messages_used += 1
    thread.last_active_turn = next_world.turn_number
    thread.trust_level = round(clamp(thread.trust_level + message_effect.trust_delta), 10)
    thread.leak_risk = round(clamp(thread.leak_risk + message_effect.leak_risk_delta), 10)
    _apply_relationship_trust(
        next_world,
        player_entity_id=player_entity_id,
        target_entity_id=target_entity_id,
        trust_delta=message_effect.trust_delta,
    )

    sequence = len(thread.message_records) + 1
    outgoing_signal = _direct_message_signal(
        next_world,
        thread,
        sender_entity_id=player_entity_id,
        recipient_entity_id=target_entity_id,
        content=message_text,
        sequence=sequence,
    )
    response_signal = _direct_message_signal(
        next_world,
        thread,
        sender_entity_id=target_entity_id,
        recipient_entity_id=player_entity_id,
        content=message_effect.response_text,
        sequence=sequence + 1,
        response_to_signal_id=outgoing_signal.signal_id,
    )
    outgoing_record = _direct_message_record(
        thread,
        signal=outgoing_signal,
        action_id="direct_backchannel_message",
        summary=message_text,
    )
    response_record = _direct_message_record(
        thread,
        signal=response_signal,
        action_id="direct_backchannel_response",
        summary=message_effect.response_text,
    )
    thread.message_records.extend([outgoing_record, response_record])
    thread.message_records = thread.message_records[-MAX_THREAD_RECORDS:]
    _append_unique(update.refreshed_thread_ids, thread.thread_id)
    _append_unique(update.message_record_ids, outgoing_record.record_id)
    _append_unique(update.message_record_ids, response_record.record_id)
    _append_unique(update.summary, f"Backchannel message sent: {thread.thread_id}.")
    _append_unique(update.summary, f"Backchannel response received: {thread.thread_id}.")
    persisted_update = _persist_backchannel_update(next_world, update)

    router = info_channel or PrototypeInfoChannel()
    routing_result = router.route_signals(next_world, [outgoing_signal, response_signal])
    return BackchannelDirectMessageResult(
        world_state=routing_result.world_state,
        accepted=True,
        target_entity_id=target_entity_id,
        thread_id=thread.thread_id,
        player_message=message_text,
        response_text=message_effect.response_text,
        routing_result=routing_result,
        update=persisted_update,
    )


def update_backchannel_threads(
    world_state: WorldStateV2,
    *,
    deterministic_result: DeterministicTurnResult,
    action_catalog: list[ActionDefinition],
    player_entity_id: str,
    thread_lifetime_turns: int = DEFAULT_THREAD_LIFETIME_TURNS,
) -> BackchannelThreadUpdate | None:
    """Open, refresh, and expire persistent backchannel threads."""

    catalog = {definition.action_id: definition for definition in action_catalog}
    update = BackchannelThreadUpdate(turn_number=world_state.turn_number)

    _expire_stale_threads(world_state, update)

    for package in _unique_packages(
        [
            *deterministic_result.accepted_actions,
            *deterministic_result.completed_pending_actions,
        ]
    ):
        if package.channel != SignalChannel.BACKCHANNEL:
            continue
        definition = catalog.get(package.action_id)
        for target_id in package.target_ids:
            if target_id == package.actor_id or target_id not in world_state.actors:
                continue
            _record_backchannel_action(
                world_state,
                update,
                package,
                target_id=target_id,
                player_entity_id=player_entity_id,
                definition=definition,
                thread_lifetime_turns=thread_lifetime_turns,
            )

    if not _has_update_content(update):
        return None
    return _persist_backchannel_update(world_state, update)


def render_backchannel_threads(world_state: WorldStateV2, *, viewer_entity_id: str) -> str:
    lines = ["BACKCHANNELS"]
    threads = [
        thread
        for thread in world_state.backchannel_threads.values()
        if viewer_entity_id in thread.participant_entity_ids
        and thread.status == BackchannelThreadStatus.OPEN
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
        lines.append(
            f"- {counterpart}: open until turn {thread.expires_turn}, "
            f"trust {thread.trust_level:.0%}, leak risk {thread.leak_risk:.0%}"
        )
        if thread.player_entity_id == viewer_entity_id:
            lines.append(
                f"  direct messages remaining: {thread.player_messages_remaining}"
            )
        if thread.message_records:
            latest = thread.message_records[-1]
            lines.append(f"  latest: {latest.summary}")
    return "\n".join(lines)


def render_backchannel_direct_message_result(
    result: BackchannelDirectMessageResult,
) -> str:
    if not result.accepted:
        lines = ["BACKCHANNEL FAILED"]
        lines.extend(f"- {error}" for error in result.errors)
        return "\n".join(lines)
    thread = result.world_state.backchannel_threads.get(result.thread_id)
    lines = [
        "BACKCHANNEL",
        f"Sent to {result.target_entity_id}: {result.player_message}",
        f"Response: {result.response_text}",
    ]
    if thread is not None:
        lines.append(
            f"Thread: {thread.player_messages_used}/{thread.max_player_messages} "
            f"direct messages used, open until turn {thread.expires_turn}."
        )
    return "\n".join(lines)


def _record_backchannel_action(
    world_state: WorldStateV2,
    update: BackchannelThreadUpdate,
    package: ActionPackage,
    *,
    target_id: str,
    player_entity_id: str,
    definition: ActionDefinition | None,
    thread_lifetime_turns: int,
) -> None:
    thread_id = backchannel_thread_id(package.actor_id, target_id)
    participant_entity_ids = sorted([package.actor_id, target_id])
    thread = world_state.backchannel_threads.get(thread_id)
    if thread is None or thread.status == BackchannelThreadStatus.EXPIRED:
        thread = BackchannelThread(
            thread_id=thread_id,
            participant_entity_ids=participant_entity_ids,
            player_entity_id=(
                player_entity_id if player_entity_id in participant_entity_ids else ""
            ),
            opened_turn=world_state.turn_number,
            last_active_turn=world_state.turn_number,
            expires_turn=world_state.turn_number + thread_lifetime_turns,
            trust_level=_initial_thread_trust(definition),
            leak_risk=_initial_thread_leak_risk(definition),
        )
        world_state.backchannel_threads[thread_id] = thread
        _append_unique(update.opened_thread_ids, thread_id)
        _append_unique(update.summary, f"Backchannel opened: {thread_id}.")
    else:
        thread.last_active_turn = world_state.turn_number
        thread.expires_turn = world_state.turn_number + thread_lifetime_turns
        _append_unique(update.refreshed_thread_ids, thread_id)
        _append_unique(update.summary, f"Backchannel refreshed: {thread_id}.")

    thread.status = BackchannelThreadStatus.OPEN
    thread.trust_level = _adjust_thread_trust(thread.trust_level, definition)
    thread.leak_risk = _adjust_thread_leak_risk(thread.leak_risk, definition)

    if package.actor_id == player_entity_id and package.metadata.get("direct_backchannel_message"):
        thread.player_messages_used = min(
            thread.max_player_messages,
            thread.player_messages_used + 1,
        )

    record = BackchannelMessageRecord(
        record_id=f"backchannel_record:{package.package_id}:{target_id}",
        turn_number=world_state.turn_number,
        sender_entity_id=package.actor_id,
        recipient_entity_ids=[target_id],
        action_id=package.action_id,
        action_package_id=package.package_id,
        summary=package.private_rationale or package.intent_summary,
        reliability=definition.signal_reliability if definition is not None else 0.75,
        leak_risk=definition.signal_leak_risk if definition is not None else 0.1,
    )
    thread.message_records.append(record)
    thread.message_records = thread.message_records[-MAX_THREAD_RECORDS:]
    _append_unique(update.message_record_ids, record.record_id)


class _DirectMessageEffect(BaseModel):
    response_text: str
    trust_delta: float = 0.0
    leak_risk_delta: float = 0.0


def _validate_direct_message(
    world_state: WorldStateV2,
    *,
    player_entity_id: str,
    target_entity_id: str,
    message_text: str,
) -> list[str]:
    errors: list[str] = []
    if player_entity_id not in world_state.actors:
        errors.append(f"unknown player entity: {player_entity_id}")
    if target_entity_id not in world_state.actors:
        errors.append(f"unknown backchannel target: {target_entity_id}")
    if target_entity_id == player_entity_id:
        errors.append("backchannel target must be another entity")
    if not message_text.strip():
        errors.append("backchannel message is empty")
    return errors


def _direct_message_effect(
    message_text: str,
    thread: BackchannelThread,
) -> _DirectMessageEffect:
    lowered = message_text.lower()
    constructive = any(
        token in lowered
        for token in [
            "guarantee",
            "non-invasion",
            "non invasion",
            "pledge",
            "reciprocal",
            "restraint",
            "save face",
            "face-saving",
            "private",
        ]
    )
    concession = any(token in lowered for token in ["jupiter", "turkey", "trade"])
    threat = any(
        token in lowered
        for token in ["ultimatum", "threat", "strike", "air strike", "invasion", "bomb"]
    )
    trust_delta = 0.0
    leak_delta = 0.0
    if constructive:
        trust_delta += 0.04
    if concession:
        trust_delta += 0.03
        leak_delta += 0.04
    if threat:
        trust_delta -= 0.06
        leak_delta += 0.03

    counterpart = _counterpart_for_response(thread)
    if threat:
        response = (
            f"{counterpart} warns that threats in this channel will harden public "
            "positions and narrow room for settlement."
        )
    elif concession:
        response = (
            f"{counterpart} asks whether any Turkey/Jupiter discussion can remain "
            "deniable and separated from public terms."
        )
    elif constructive:
        response = (
            f"{counterpart} says concrete reciprocal terms may be possible if the "
            "exit stays private and neither side is publicly humiliated."
        )
    elif thread.trust_level >= 0.6:
        response = (
            f"{counterpart} keeps the channel open and asks for a more specific "
            "settlement formula."
        )
    else:
        response = (
            f"{counterpart} acknowledges the message but offers no firm concession yet."
        )
    return _DirectMessageEffect(
        response_text=response,
        trust_delta=trust_delta,
        leak_risk_delta=leak_delta,
    )


def _counterpart_for_response(thread: BackchannelThread) -> str:
    for participant_id in thread.participant_entity_ids:
        if participant_id != thread.player_entity_id:
            return participant_id
    return "The counterpart"


def _direct_message_signal(
    world_state: WorldStateV2,
    thread: BackchannelThread,
    *,
    sender_entity_id: str,
    recipient_entity_id: str,
    content: str,
    sequence: int,
    response_to_signal_id: str = "",
) -> Signal:
    signal_id = (
        f"sig_{world_state.turn_number}_{thread.thread_id.replace(':', '_')}_"
        f"direct_{sequence}"
    )
    metadata: dict[str, str | int | float | bool] = {
        "backchannel_thread_id": thread.thread_id,
        "direct_backchannel_message": True,
    }
    if response_to_signal_id:
        metadata["response_to_signal_id"] = response_to_signal_id
    return Signal(
        signal_id=signal_id,
        source_entity_id=sender_entity_id,
        recipient_entity_ids=[recipient_entity_id],
        channel=SignalChannel.BACKCHANNEL,
        payload_type=PayloadType.BACKCHANNEL_MESSAGE,
        content=content,
        truth_reference_id=thread.thread_id,
        emitted_turn=world_state.turn_number,
        intended_arrival_turn=world_state.turn_number,
        visibility=SignalVisibility.COVERT,
        reliability=max(0.25, thread.trust_level),
        deniability=0.8,
        leak_risk=thread.leak_risk,
        distortion_risk=0.12,
        urgency=0.55,
        classification="confidential",
        metadata=metadata,
    )


def _direct_message_record(
    thread: BackchannelThread,
    *,
    signal: Signal,
    action_id: str,
    summary: str,
) -> BackchannelMessageRecord:
    return BackchannelMessageRecord(
        record_id=f"backchannel_record:{signal.signal_id}",
        turn_number=signal.emitted_turn,
        sender_entity_id=signal.source_entity_id,
        recipient_entity_ids=signal.recipient_entity_ids,
        action_id=action_id,
        action_package_id=signal.signal_id,
        summary=summary,
        reliability=signal.reliability,
        leak_risk=signal.leak_risk,
    )


def _apply_relationship_trust(
    world_state: WorldStateV2,
    *,
    player_entity_id: str,
    target_entity_id: str,
    trust_delta: float,
) -> None:
    if abs(trust_delta) < 0.0001:
        return
    for source_id, destination_id in [
        (player_entity_id, target_entity_id),
        (target_entity_id, player_entity_id),
    ]:
        key = f"{source_id}->{destination_id}"
        pair = world_state.relationships.setdefault(key, {})
        pair["trust"] = round(clamp(float(pair.get("trust", 0.0)) + trust_delta), 10)


def _expire_stale_threads(
    world_state: WorldStateV2,
    update: BackchannelThreadUpdate,
) -> None:
    for thread in world_state.backchannel_threads.values():
        if thread.status != BackchannelThreadStatus.OPEN:
            continue
        if thread.expires_turn >= world_state.turn_number:
            continue
        thread.status = BackchannelThreadStatus.EXPIRED
        _append_unique(update.expired_thread_ids, thread.thread_id)
        _append_unique(update.summary, f"Backchannel expired: {thread.thread_id}.")


def _persist_backchannel_update(
    world_state: WorldStateV2,
    update: BackchannelThreadUpdate,
) -> BackchannelThreadUpdate | None:
    if not _has_update_content(update):
        return None
    world_state.backchannel_update_history.append(update)
    if len(world_state.backchannel_update_history) > MAX_BACKCHANNEL_UPDATE_HISTORY:
        world_state.backchannel_update_history = world_state.backchannel_update_history[
            -MAX_BACKCHANNEL_UPDATE_HISTORY:
        ]
    return update


def _initial_thread_trust(definition: ActionDefinition | None) -> float:
    if definition is None:
        return 0.5
    return round(clamp(0.45 + definition.deescalation_potential * 0.25), 10)


def _initial_thread_leak_risk(definition: ActionDefinition | None) -> float:
    if definition is None:
        return 0.1
    return round(clamp(definition.signal_leak_risk), 10)


def _adjust_thread_trust(
    trust_level: float,
    definition: ActionDefinition | None,
) -> float:
    if definition is None:
        return trust_level
    delta = definition.deescalation_potential * 0.08 - definition.escalation_risk * 0.04
    return round(clamp(trust_level + delta), 10)


def _adjust_thread_leak_risk(
    leak_risk: float,
    definition: ActionDefinition | None,
) -> float:
    if definition is None:
        return leak_risk
    return round(clamp(max(leak_risk, definition.signal_leak_risk)), 10)


def _unique_packages(packages: list[ActionPackage]) -> list[ActionPackage]:
    seen: set[str] = set()
    unique: list[ActionPackage] = []
    for package in packages:
        if package.package_id in seen:
            continue
        seen.add(package.package_id)
        unique.append(package)
    return unique


def _has_update_content(update: BackchannelThreadUpdate) -> bool:
    return bool(
        update.opened_thread_ids
        or update.refreshed_thread_ids
        or update.expired_thread_ids
        or update.message_record_ids
    )


def _append_unique(values: list[str], value: str) -> None:
    if value and value not in values:
        values.append(value)


def _normalize_target_query(value: str) -> str:
    return value.strip().lower().replace("_", " ")
