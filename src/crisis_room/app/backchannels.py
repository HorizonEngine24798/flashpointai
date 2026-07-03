from __future__ import annotations

from pydantic import BaseModel, Field

from crisis_room.agents.context import build_task_request, build_visible_context
from crisis_room.agents.gamemaster import GamemasterCompilation
from crisis_room.agents.info_channel import PrototypeInfoChannel, RoutingResult
from crisis_room.config.gameplay import (
    BACKCHANNEL_BASE_TRUST,
    BACKCHANNEL_DEESCALATION_TRUST_SCALE,
    BACKCHANNEL_REFRESH_DEESCALATION_SCALE,
    BACKCHANNEL_REFRESH_ESCALATION_SCALE,
    BACKCHANNEL_TRUST_DELTA_THRESHOLD,
    CONCESSION_MESSAGE_LEAK_DELTA,
    CONCESSION_MESSAGE_TRUST_DELTA,
    CONSTRUCTIVE_MESSAGE_TRUST_DELTA,
    DEFAULT_BACKCHANNEL_DIRECT_MESSAGE_BUDGET,
    DEFAULT_BACKCHANNEL_LEAK_RISK,
    DEFAULT_BACKCHANNEL_THREAD_LIFETIME_TURNS,
    DEFAULT_BACKCHANNEL_TRUST,
    DIRECT_MESSAGE_DENIABILITY,
    DIRECT_MESSAGE_DISTORTION_RISK,
    DIRECT_MESSAGE_MIN_RELIABILITY,
    DIRECT_MESSAGE_URGENCY,
    MAX_BACKCHANNEL_THREAD_RECORDS,
    MAX_BACKCHANNEL_UPDATE_HISTORY,
    NUMERIC_ROUND_DIGITS,
    THREAT_MESSAGE_LEAK_DELTA,
    THREAT_MESSAGE_TRUST_DELTA,
)
from crisis_room.engine.actions import (
    ActionDefinition,
    ActionPackage,
    ActionResolver,
    ScenarioCapability,
)
from crisis_room.engine.adjudication import DeterministicEngineV2, DeterministicTurnResult
from crisis_room.engine.clocks import clamp
from crisis_room.llm.contracts import LLMClient
from crisis_room.llm.task_contracts import (
    BackchannelAvailabilityCheck,
    BackchannelCounterpartResponse,
    BackchannelStateChange,
)
from crisis_room.state.backchannels import (
    BackchannelMessageRecord,
    BackchannelThread,
    BackchannelThreadStatus,
    BackchannelThreadUpdate,
    backchannel_message_leak_risk,
)
from crisis_room.state.beliefs import BeliefClaim
from crisis_room.state.signals import PayloadType, Signal, SignalChannel, SignalVisibility
from crisis_room.state.world import WorldStateV2


FORMAL_BACKCHANNEL_CAPABILITY_ID = "cuba_direct_kremlin_message"

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


class BackchannelDirectMessageResult(BaseModel):
    world_state: WorldStateV2
    accepted: bool
    available: bool = False
    errors: list[str] = Field(default_factory=list)
    target_entity_id: str = ""
    target_label: str = ""
    thread_id: str = ""
    player_message: str = ""
    response_text: str = ""
    availability: BackchannelAvailabilityCheck | None = None
    counterpart_response: BackchannelCounterpartResponse | None = None
    state_change: BackchannelStateChange | None = None
    routing_result: RoutingResult | None = None
    update: BackchannelThreadUpdate | None = None


class BackchannelMessagePreparation(BaseModel):
    accepted: bool
    formal: bool = False
    errors: list[str] = Field(default_factory=list)
    target_entity_id: str = ""
    thread_id: str = ""
    message_text: str = ""
    compilation: GamemasterCompilation | None = None
    counterpart_response: BackchannelCounterpartResponse | None = None


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


def prepare_backchannel_message(
    world_state: WorldStateV2,
    *,
    player_entity_id: str,
    target_entity_id: str,
    message_text: str,
    action_catalog: list[ActionDefinition],
    capabilities: list[ScenarioCapability],
    llm_client: LLMClient,
) -> BackchannelMessagePreparation:
    """Validate a direct message and compile it if it is mechanically formal."""

    errors = _validate_direct_message(
        world_state,
        player_entity_id=player_entity_id,
        target_entity_id=target_entity_id,
        message_text=message_text,
    )
    thread_id = backchannel_thread_id(player_entity_id, target_entity_id)
    if errors:
        return BackchannelMessagePreparation(
            accepted=False,
            errors=errors,
            target_entity_id=target_entity_id,
            thread_id=thread_id,
            message_text=message_text,
        )
    if not _is_formal_backchannel_message(message_text):
        return BackchannelMessagePreparation(
            accepted=True,
            formal=False,
            target_entity_id=target_entity_id,
            thread_id=thread_id,
            message_text=message_text,
        )

    thread = world_state.backchannel_threads.get(thread_id)
    _validate_thread_for_direct_message(
        world_state,
        target_entity_id=target_entity_id,
        thread=thread,
        errors=errors,
    )
    if errors:
        return BackchannelMessagePreparation(
            accepted=False,
            formal=True,
            errors=errors,
            target_entity_id=target_entity_id,
            thread_id=thread_id,
            message_text=message_text,
        )

    assert thread is not None
    counterpart_response = _request_counterpart_response(
        world_state,
        player_entity_id=player_entity_id,
        target_entity_id=target_entity_id,
        message_text=message_text,
        thread=thread,
        action_catalog=action_catalog,
        capabilities=capabilities,
        llm_client=llm_client,
    )
    package = _formal_backchannel_action_package(
        world_state,
        player_entity_id=player_entity_id,
        target_entity_id=target_entity_id,
        message_text=message_text,
        thread=thread,
        counterpart_response=counterpart_response,
    )
    validation = DeterministicEngineV2(action_catalog, capabilities).validate_action(
        world_state,
        package,
    )
    if not validation.is_valid:
        return BackchannelMessagePreparation(
            accepted=False,
            formal=True,
            errors=validation.errors,
            target_entity_id=target_entity_id,
            thread_id=thread_id,
            message_text=message_text,
            counterpart_response=counterpart_response,
        )

    compilation = GamemasterCompilation(
        action_packages=[package],
        action_package=package,
        compiled_intents=[package.intent_summary],
        notes=[
            "Compiled direct backchannel message as a formal scenario capability.",
            *[f"validation warning: {warning}" for warning in validation.warnings],
        ],
    )
    return BackchannelMessagePreparation(
        accepted=True,
        formal=True,
        target_entity_id=target_entity_id,
        thread_id=thread_id,
        message_text=message_text,
        compilation=compilation,
        counterpart_response=counterpart_response,
    )


def send_backchannel_message(
    world_state: WorldStateV2,
    *,
    player_entity_id: str,
    target_entity_id: str = "",
    target_query: str = "",
    message_text: str,
    action_catalog: list[ActionDefinition] | None = None,
    capabilities: list[ScenarioCapability] | None = None,
    llm_client: LLMClient | None = None,
    info_channel: PrototypeInfoChannel | None = None,
) -> BackchannelDirectMessageResult:
    """Send one scarce direct message through a target-specific backchannel."""

    next_world = world_state.model_copy(deep=True)
    update = BackchannelThreadUpdate(turn_number=next_world.turn_number)
    _expire_stale_threads(next_world, update)

    target_label = (target_query or target_entity_id).strip()
    errors = _validate_direct_message_request(
        next_world,
        player_entity_id=player_entity_id,
        target_label=target_label,
        message_text=message_text,
    )
    availability: BackchannelAvailabilityCheck | None = None
    if not errors and _backchannel_exchange_used_this_turn(
        next_world,
        player_entity_id=player_entity_id,
    ):
        errors.append("direct message budget is exhausted for this turn")
    if not errors:
        availability = (
            _request_backchannel_availability(
                next_world,
                player_entity_id=player_entity_id,
                target_query=target_label,
                message_text=message_text,
                action_catalog=action_catalog or [],
                capabilities=capabilities or [],
                llm_client=llm_client,
            )
            if llm_client is not None
            else _fallback_backchannel_availability(
                next_world,
                player_entity_id=player_entity_id,
                target_query=target_label,
            )
        )
        target_entity_id = availability.target_entity_id.strip()
        target_label = availability.target_label or target_label
        if not availability.allowed:
            errors.append(
                availability.reason
                or f"backchannel message is not allowed for {target_label}"
            )
        elif not availability.available or not target_entity_id:
            errors.append(
                availability.reason
                or f"backchannel target is not available: {target_label}"
            )

    if not errors:
        errors = _validate_direct_message(
            next_world,
            player_entity_id=player_entity_id,
            target_entity_id=target_entity_id,
            message_text=message_text,
        )

    thread_id = (
        backchannel_thread_id(player_entity_id, target_entity_id)
        if target_entity_id
        else ""
    )
    thread = next_world.backchannel_threads.get(thread_id) if thread_id else None
    if not errors:
        if thread is None or thread.status == BackchannelThreadStatus.EXPIRED:
            thread = _open_direct_backchannel_thread(
                next_world,
                update,
                player_entity_id=player_entity_id,
                target_entity_id=target_entity_id,
            )
        _reset_thread_message_budget_for_turn(thread, next_world.turn_number)
        if thread.status != BackchannelThreadStatus.OPEN:
            errors.append(f"backchannel thread with {target_entity_id} is not open")
        elif thread.expires_turn < next_world.turn_number:
            thread.status = BackchannelThreadStatus.EXPIRED
            _append_unique(update.expired_thread_ids, thread.thread_id)
            _append_unique(update.summary, f"Backchannel expired: {thread.thread_id}.")
            errors.append(f"backchannel thread with {target_entity_id} has expired")
        elif thread.player_messages_remaining_for_turn(next_world.turn_number) <= 0:
            errors.append(f"direct message budget is exhausted for {target_entity_id}")

    if errors:
        persisted_update = _persist_backchannel_update(next_world, update)
        return BackchannelDirectMessageResult(
            world_state=next_world,
            accepted=False,
            available=bool(availability and availability.available),
            errors=errors,
            target_entity_id=target_entity_id,
            target_label=target_label,
            thread_id=thread_id,
            player_message=message_text,
            availability=availability,
            update=persisted_update,
        )

    assert thread is not None
    counterpart_response: BackchannelCounterpartResponse | None = None
    state_change: BackchannelStateChange | None = None
    if llm_client is not None:
        counterpart_response = _request_counterpart_response(
            next_world,
            player_entity_id=player_entity_id,
            target_entity_id=target_entity_id,
            message_text=message_text,
            thread=thread,
            action_catalog=action_catalog or [],
            capabilities=capabilities or [],
            llm_client=llm_client,
        )
        state_change = _request_backchannel_state_change(
            next_world,
            player_entity_id=player_entity_id,
            target_entity_id=target_entity_id,
            message_text=message_text,
            response=counterpart_response,
            thread=thread,
            action_catalog=action_catalog or [],
            capabilities=capabilities or [],
            llm_client=llm_client,
        )
        message_effect = _DirectMessageEffect(
            response_text=counterpart_response.response_text,
            trust_delta=state_change.trust_delta,
            leak_risk_delta=state_change.leak_risk_delta,
        )
        relationship_delta = state_change.relationship_delta or state_change.trust_delta
    else:
        message_effect = _direct_message_effect(message_text, thread)
        relationship_delta = message_effect.trust_delta

    thread.player_messages_used += 1
    thread.player_message_turn = next_world.turn_number
    thread.last_active_turn = next_world.turn_number
    thread.trust_level = round(
        clamp(thread.trust_level + message_effect.trust_delta),
        NUMERIC_ROUND_DIGITS,
    )
    thread.leak_risk = round(
        clamp(thread.leak_risk + message_effect.leak_risk_delta),
        NUMERIC_ROUND_DIGITS,
    )
    _apply_relationship_trust(
        next_world,
        player_entity_id=player_entity_id,
        target_entity_id=target_entity_id,
        trust_delta=relationship_delta,
    )
    if state_change is not None:
        _apply_backchannel_state_change(
            next_world,
            target_entity_id=target_entity_id,
            state_change=state_change,
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
    thread.message_records = thread.message_records[-MAX_BACKCHANNEL_THREAD_RECORDS:]
    _append_unique(update.refreshed_thread_ids, thread.thread_id)
    _append_unique(update.message_record_ids, outgoing_record.record_id)
    _append_unique(update.message_record_ids, response_record.record_id)
    _append_unique(update.summary, f"Backchannel message sent: {thread.thread_id}.")
    _append_unique(update.summary, f"Backchannel response received: {thread.thread_id}.")
    _mark_backchannel_exchange_used(next_world, player_entity_id=player_entity_id)
    persisted_update = _persist_backchannel_update(next_world, update)

    router = info_channel or PrototypeInfoChannel()
    routing_result = router.route_signals(next_world, [outgoing_signal, response_signal])
    return BackchannelDirectMessageResult(
        world_state=routing_result.world_state,
        accepted=True,
        available=True,
        target_entity_id=target_entity_id,
        target_label=target_label,
        thread_id=thread.thread_id,
        player_message=message_text,
        response_text=message_effect.response_text,
        availability=availability,
        counterpart_response=counterpart_response,
        state_change=state_change,
        routing_result=routing_result,
        update=persisted_update,
    )


def update_backchannel_threads(
    world_state: WorldStateV2,
    *,
    deterministic_result: DeterministicTurnResult,
    action_catalog: list[ActionDefinition],
    capabilities: list[ScenarioCapability] | None = None,
    player_entity_id: str,
    thread_lifetime_turns: int = DEFAULT_BACKCHANNEL_THREAD_LIFETIME_TURNS,
) -> BackchannelThreadUpdate | None:
    """Open, refresh, and expire persistent backchannel threads."""

    resolver = ActionResolver(action_catalog, capabilities)
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
        definition = _resolve_definition(resolver, package)
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


def build_formal_backchannel_response_signals(
    world_state: WorldStateV2,
    *,
    deterministic_result: DeterministicTurnResult,
) -> list[Signal]:
    signals: list[Signal] = []
    outgoing_by_package = {
        signal.truth_reference_id: signal
        for signal in deterministic_result.emitted_signals
        if signal.truth_reference_id
    }
    for package in _unique_packages(
        [
            *deterministic_result.accepted_actions,
            *deterministic_result.completed_pending_actions,
        ]
    ):
        if not package.metadata.get("formal_backchannel_message"):
            continue
        if not package.target_ids:
            continue
        response_text = str(package.metadata.get("counterpart_response_text", "")).strip()
        if not response_text:
            continue
        target_id = package.target_ids[0]
        thread_id = str(
            package.metadata.get(
                "backchannel_thread_id",
                backchannel_thread_id(package.actor_id, target_id),
            )
        )
        thread = world_state.backchannel_threads.get(thread_id)
        leak_delta = _metadata_float(package.metadata, "counterpart_leak_risk_delta")
        leak_risk = clamp(
            (
                backchannel_message_leak_risk(thread)
                if thread is not None
                else DEFAULT_BACKCHANNEL_LEAK_RISK
            )
            + leak_delta
        )
        outgoing_signal = outgoing_by_package.get(package.package_id)
        metadata: dict[str, str | int | float | bool] = {
            "action_id": package.action_id,
            "capability_id": package.capability_id or "",
            "backchannel_thread_id": thread_id,
            "direct_backchannel_message": True,
            "formal_backchannel_response": True,
            "leak_summary": _direct_message_leak_summary(target_id, package.actor_id),
        }
        if outgoing_signal is not None:
            metadata["response_to_signal_id"] = outgoing_signal.signal_id
        signals.append(
            Signal(
                signal_id=f"sig_{world_state.turn_number}_{package.package_id}_formal_response",
                source_entity_id=target_id,
                recipient_entity_ids=[package.actor_id],
                channel=SignalChannel.BACKCHANNEL,
                payload_type=PayloadType.BACKCHANNEL_MESSAGE,
                content=response_text,
                truth_reference_id=package.package_id,
                emitted_turn=world_state.turn_number,
                intended_arrival_turn=world_state.turn_number,
                visibility=SignalVisibility.COVERT,
                reliability=max(
                    DIRECT_MESSAGE_MIN_RELIABILITY,
                    thread.trust_level if thread is not None else DEFAULT_BACKCHANNEL_TRUST,
                ),
                deniability=DIRECT_MESSAGE_DENIABILITY,
                leak_risk=round(leak_risk, NUMERIC_ROUND_DIGITS),
                distortion_risk=DIRECT_MESSAGE_DISTORTION_RISK,
                urgency=DIRECT_MESSAGE_URGENCY,
                classification="confidential",
                metadata=metadata,
            )
        )
    return signals


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
                "  direct messages remaining: "
                f"{thread.player_messages_remaining_for_turn(world_state.turn_number)}"
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
            max_player_messages=_message_budget(definition),
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
        _reset_thread_message_budget_for_turn(thread, world_state.turn_number)
        thread.player_messages_used = min(
            thread.max_player_messages,
            thread.player_messages_used + 1,
        )
        thread.player_message_turn = world_state.turn_number
        trust_delta = _metadata_float(package.metadata, "counterpart_trust_delta")
        relationship_delta = _metadata_float(
            package.metadata,
            "counterpart_relationship_delta",
        )
        leak_delta = _metadata_float(package.metadata, "counterpart_leak_risk_delta")
        if package.metadata.get("formal_backchannel_message"):
            thread.trust_level = round(
                clamp(thread.trust_level + trust_delta),
                NUMERIC_ROUND_DIGITS,
            )
            thread.leak_risk = round(
                clamp(thread.leak_risk + leak_delta),
                NUMERIC_ROUND_DIGITS,
            )
            _apply_relationship_trust(
                world_state,
                player_entity_id=package.actor_id,
                target_entity_id=target_id,
                trust_delta=relationship_delta or trust_delta,
            )

    record = BackchannelMessageRecord(
        record_id=f"backchannel_record:{package.package_id}:{target_id}",
        turn_number=world_state.turn_number,
        sender_entity_id=package.actor_id,
        recipient_entity_ids=[target_id],
        action_id=package.mechanical_id,
        action_package_id=package.package_id,
        summary=package.private_rationale or package.intent_summary,
        reliability=definition.signal_reliability if definition is not None else 0.75,
        leak_risk=(
            definition.signal_leak_risk
            if definition is not None
            else DEFAULT_BACKCHANNEL_LEAK_RISK
        ),
    )
    thread.message_records.append(record)
    response_text = str(package.metadata.get("counterpart_response_text", "")).strip()
    if package.metadata.get("formal_backchannel_message") and response_text:
        response_record = BackchannelMessageRecord(
            record_id=f"backchannel_record:{package.package_id}:{target_id}:response",
            turn_number=world_state.turn_number,
            sender_entity_id=target_id,
            recipient_entity_ids=[package.actor_id],
            action_id="direct_backchannel_response",
            action_package_id=package.package_id,
            summary=response_text,
            reliability=record.reliability,
            leak_risk=thread.leak_risk,
        )
        thread.message_records.append(response_record)
        _append_unique(update.message_record_ids, response_record.record_id)
        _append_unique(update.summary, f"Backchannel response received: {thread.thread_id}.")
    thread.message_records = thread.message_records[-MAX_BACKCHANNEL_THREAD_RECORDS:]
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


def _validate_direct_message_request(
    world_state: WorldStateV2,
    *,
    player_entity_id: str,
    target_label: str,
    message_text: str,
) -> list[str]:
    errors: list[str] = []
    if player_entity_id not in world_state.actors:
        errors.append(f"unknown player entity: {player_entity_id}")
    if not target_label:
        errors.append("backchannel target is empty")
    if _normalize_target_query(target_label) == _normalize_target_query(player_entity_id):
        errors.append("backchannel target must be another entity")
    if not message_text.strip():
        errors.append("backchannel message is empty")
    return errors


def _validate_thread_for_direct_message(
    world_state: WorldStateV2,
    *,
    target_entity_id: str,
    thread: BackchannelThread | None,
    errors: list[str],
) -> None:
    if errors:
        return
    if thread is None:
        errors.append(f"no active backchannel thread with {target_entity_id}")
        return
    if thread.status != BackchannelThreadStatus.OPEN:
        errors.append(f"backchannel thread with {target_entity_id} is not open")
        return
    if thread.expires_turn < world_state.turn_number:
        errors.append(f"backchannel thread with {target_entity_id} has expired")
        return
    if thread.player_messages_remaining_for_turn(world_state.turn_number) <= 0:
        errors.append(f"direct message budget is exhausted for {target_entity_id}")


def _request_backchannel_availability(
    world_state: WorldStateV2,
    *,
    player_entity_id: str,
    target_query: str,
    message_text: str,
    action_catalog: list[ActionDefinition],
    capabilities: list[ScenarioCapability],
    llm_client: LLMClient,
) -> BackchannelAvailabilityCheck:
    player = world_state.actors[player_entity_id]
    visible_context = build_visible_context(
        player,
        world_state,
        action_catalog=action_catalog,
        capabilities=capabilities,
        player_message=message_text,
        extra={
            "backchannel_target_query": target_query,
            "available_actor_ids": [
                entity_id
                for entity_id in world_state.actors
                if entity_id != player_entity_id
            ],
        },
    )
    request = build_task_request(
        label=f"backchannel.{player_entity_id}.availability",
        system_prompt=(
            "You are the gamemaster checking whether a direct backchannel message "
            "can reach a scenario actor. The target can be free-form, but available "
            "targets must map to an actor with gamestate."
        ),
        visible_context=visible_context,
        task_instruction=(
            "Return a BackchannelAvailabilityCheck for the requested target. "
            "Set allowed true for ordinary attempts even if no scenario actor is "
            "available. Set available true only when target_entity_id exactly "
            "matches a visible actor other than the player. Family members, aides, "
            "or unnamed intermediaries without actor gamestate should be allowed "
            "but unavailable."
        ),
        response_schema_name="BackchannelAvailabilityCheck",
        metadata={
            "agent": "backchannel_availability",
            "player_entity_id": player_entity_id,
            "turn_number": world_state.turn_number,
        },
        max_tokens=500,
    )
    return llm_client.complete_json(request, BackchannelAvailabilityCheck)


def _fallback_backchannel_availability(
    world_state: WorldStateV2,
    *,
    player_entity_id: str,
    target_query: str,
) -> BackchannelAvailabilityCheck:
    target_entity_id = resolve_backchannel_target(
        world_state,
        player_entity_id=player_entity_id,
        target_query=target_query,
    )
    if target_entity_id is None:
        return BackchannelAvailabilityCheck(
            allowed=True,
            available=False,
            target_label=target_query,
            reason="Target has no scenario actor gamestate.",
            confidence=0.7,
        )
    actor = world_state.actors[target_entity_id]
    return BackchannelAvailabilityCheck(
        allowed=True,
        available=True,
        target_entity_id=target_entity_id,
        target_label=actor.name,
        reason="Target maps to a scenario actor with gamestate.",
        confidence=0.9,
    )


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
        system_prompt=(
            "You are the gamemaster resolving bounded actor-local consequences "
            "from one completed backchannel exchange. Do not resolve formal actions."
        ),
        visible_context=visible_context,
        task_instruction=(
            "Return a BackchannelStateChange for the target actor. Apply only "
            "changes that follow from the message and response: belief updates, "
            "one memory note, one unresolved thread, and small relationship or "
            "leak-risk deltas. Leave fields empty or zero when nothing changes."
        ),
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


def _apply_backchannel_state_change(
    world_state: WorldStateV2,
    *,
    target_entity_id: str,
    state_change: BackchannelStateChange,
) -> None:
    actor = world_state.actors[target_entity_id]
    if state_change.memory_note:
        actor.memory_summary = _merge_entity_memory(
            actor.memory_summary,
            state_change.memory_note,
        )
    if state_change.unresolved_thread:
        _append_unique(actor.unresolved_threads, state_change.unresolved_thread)
        actor.unresolved_threads = actor.unresolved_threads[-8:]
    for update in state_change.belief_updates:
        actor.beliefs.upsert_claim(
            BeliefClaim(
                topic=update.topic,
                summary=update.summary,
                confidence=update.confidence,
                source_signal_ids=list(update.source_signal_ids),
                last_updated_turn=world_state.turn_number,
            )
        )
    summary = state_change.memory_note or state_change.unresolved_thread
    if summary:
        world_state.append_entity_timeline(
            target_entity_id,
            "Backchannel Exchange Assessed",
            summary,
            source="gamemaster",
            tags=["backchannel", "state_update"],
        )


def _merge_entity_memory(existing: str, note: str) -> str:
    text = note.strip()
    if not text:
        return existing
    if not existing.strip():
        return text
    if text in existing:
        return existing
    merged = f"{existing.strip()} {text}"
    return merged[-700:]


def _open_direct_backchannel_thread(
    world_state: WorldStateV2,
    update: BackchannelThreadUpdate,
    *,
    player_entity_id: str,
    target_entity_id: str,
) -> BackchannelThread:
    thread_id = backchannel_thread_id(player_entity_id, target_entity_id)
    thread = BackchannelThread(
        thread_id=thread_id,
        participant_entity_ids=sorted([player_entity_id, target_entity_id]),
        player_entity_id=player_entity_id,
        opened_turn=world_state.turn_number,
        last_active_turn=world_state.turn_number,
        expires_turn=world_state.turn_number + DEFAULT_BACKCHANNEL_THREAD_LIFETIME_TURNS,
        trust_level=DEFAULT_BACKCHANNEL_TRUST,
        leak_risk=DEFAULT_BACKCHANNEL_LEAK_RISK,
        max_player_messages=DEFAULT_BACKCHANNEL_DIRECT_MESSAGE_BUDGET,
    )
    world_state.backchannel_threads[thread_id] = thread
    _append_unique(update.opened_thread_ids, thread_id)
    _append_unique(update.summary, f"Backchannel opened: {thread_id}.")
    return thread


def _reset_thread_message_budget_for_turn(
    thread: BackchannelThread,
    turn_number: int,
) -> None:
    if thread.player_message_turn != turn_number:
        thread.player_messages_used = 0


def _backchannel_exchange_used_this_turn(
    world_state: WorldStateV2,
    *,
    player_entity_id: str,
) -> bool:
    return (
        world_state.metadata.get(_backchannel_exchange_turn_key(player_entity_id))
        == world_state.turn_number
    )


def _mark_backchannel_exchange_used(
    world_state: WorldStateV2,
    *,
    player_entity_id: str,
) -> None:
    world_state.metadata[_backchannel_exchange_turn_key(player_entity_id)] = (
        world_state.turn_number
    )


def _backchannel_exchange_turn_key(player_entity_id: str) -> str:
    return f"backchannel_exchange_turn:{player_entity_id}"


def _is_formal_backchannel_message(message_text: str) -> bool:
    lowered = message_text.strip().lower()
    if any(lowered.startswith(prefix) for prefix in _FORMAL_BACKCHANNEL_PREFIXES):
        return True
    return any(token in lowered for token in _FORMAL_BACKCHANNEL_TOKENS)


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
        system_prompt=(
            "You are the recipient of a direct backchannel message in a crisis "
            "simulation. Reply as the target entity through the same covert channel. "
            "Do not resolve deterministic game effects."
        ),
        visible_context=visible_context,
        task_instruction=(
            "Return a BackchannelCounterpartResponse to the incoming direct message. "
            "Keep response_text concise enough to be routed as one backchannel signal. "
            "Use the delta fields only as bounded hints about tone, trust, and leak "
            "pressure."
        ),
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
        capability_id=FORMAL_BACKCHANNEL_CAPABILITY_ID,
        target_ids=[target_entity_id],
        channel=SignalChannel.BACKCHANNEL,
        intent_summary=clean_message,
        private_rationale=clean_message,
        submitted_turn=world_state.turn_number,
        commitment_level=0.55,
        risk_acceptance=0.45,
        metadata={
            "created_by": "prepare_backchannel_message",
            "direct_backchannel_message": True,
            "formal_backchannel_message": True,
            "backchannel_thread_id": thread.thread_id,
            "counterpart_response_text": counterpart_response.response_text,
            "counterpart_trust_delta": counterpart_response.trust_delta,
            "counterpart_leak_risk_delta": counterpart_response.leak_risk_delta,
            "counterpart_relationship_delta": counterpart_response.relationship_delta,
            "counterpart_accepted": counterpart_response.accepted,
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
        trust_delta += CONSTRUCTIVE_MESSAGE_TRUST_DELTA
    if concession:
        trust_delta += CONCESSION_MESSAGE_TRUST_DELTA
        leak_delta += CONCESSION_MESSAGE_LEAK_DELTA
    if threat:
        trust_delta += THREAT_MESSAGE_TRUST_DELTA
        leak_delta += THREAT_MESSAGE_LEAK_DELTA

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
        "leak_summary": _direct_message_leak_summary(
            sender_entity_id,
            recipient_entity_id,
        ),
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
        reliability=max(DIRECT_MESSAGE_MIN_RELIABILITY, thread.trust_level),
        deniability=DIRECT_MESSAGE_DENIABILITY,
        leak_risk=backchannel_message_leak_risk(thread),
        distortion_risk=DIRECT_MESSAGE_DISTORTION_RISK,
        urgency=DIRECT_MESSAGE_URGENCY,
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
    if abs(trust_delta) < BACKCHANNEL_TRUST_DELTA_THRESHOLD:
        return
    for source_id, destination_id in [
        (player_entity_id, target_entity_id),
        (target_entity_id, player_entity_id),
    ]:
        key = f"{source_id}->{destination_id}"
        pair = world_state.relationships.setdefault(key, {})
        pair["trust"] = round(
            clamp(float(pair.get("trust", 0.0)) + trust_delta),
            NUMERIC_ROUND_DIGITS,
        )


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
        return DEFAULT_BACKCHANNEL_TRUST
    return round(
        clamp(
            BACKCHANNEL_BASE_TRUST
            + definition.deescalation_potential * BACKCHANNEL_DEESCALATION_TRUST_SCALE
        ),
        NUMERIC_ROUND_DIGITS,
    )


def _initial_thread_leak_risk(definition: ActionDefinition | None) -> float:
    if definition is None:
        return DEFAULT_BACKCHANNEL_LEAK_RISK
    return round(clamp(definition.signal_leak_risk), NUMERIC_ROUND_DIGITS)


def _message_budget(definition: ActionDefinition | None) -> int:
    if definition is None:
        return DEFAULT_BACKCHANNEL_DIRECT_MESSAGE_BUDGET
    return int(
        definition.message_budget.get(
            "player_messages",
            DEFAULT_BACKCHANNEL_DIRECT_MESSAGE_BUDGET,
        )
    )


def _adjust_thread_trust(
    trust_level: float,
    definition: ActionDefinition | None,
) -> float:
    if definition is None:
        return trust_level
    delta = (
        definition.deescalation_potential * BACKCHANNEL_REFRESH_DEESCALATION_SCALE
        - definition.escalation_risk * BACKCHANNEL_REFRESH_ESCALATION_SCALE
    )
    return round(clamp(trust_level + delta), NUMERIC_ROUND_DIGITS)


def _adjust_thread_leak_risk(
    leak_risk: float,
    definition: ActionDefinition | None,
) -> float:
    if definition is None:
        return leak_risk
    return round(
        clamp(max(leak_risk, definition.signal_leak_risk)),
        NUMERIC_ROUND_DIGITS,
    )


def _resolve_definition(
    resolver: ActionResolver,
    package: ActionPackage,
) -> ActionDefinition | None:
    definition, errors = resolver.resolve_package(package)
    return None if errors else definition


def _metadata_float(
    metadata: dict[str, str | int | float | bool],
    key: str,
    default: float = 0.0,
) -> float:
    value = metadata.get(key, default)
    if isinstance(value, bool):
        return default
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


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
