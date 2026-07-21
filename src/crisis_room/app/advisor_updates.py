from __future__ import annotations

from crisis_room.agents.base import AgentOutput
from crisis_room.agents.info_channel import RoutingResult
from crisis_room.config.gameplay import (
    ADVISOR_BASE_CHANNEL_TRUST,
    ADVISOR_BELIEF_CONFIDENCE_STEP,
    ADVISOR_DELTA_CLAMP,
    ADVISOR_DELTA_ROUND_DIGITS,
    ADVISOR_METRIC_CHANGE_THRESHOLD,
    ADVISOR_SCALE_CLAMP,
    ADVISOR_SUMMARY_CHANGE_THRESHOLD,
    ADVISOR_SUMMARY_LIMIT,
    ADVISOR_VALUE_CHANGE_THRESHOLD,
    MAX_ADVISOR_RECENT_NOTES,
    MAX_ADVISOR_UPDATE_HISTORY,
    NUMERIC_ROUND_DIGITS,
)
from crisis_room.engine.actions import (
    ActionCategory,
    ActionDefinition,
    ActionPackage,
    ActionResolver,
    ScenarioCapability,
)
from crisis_room.engine.adjudication import DeterministicTurnResult
from crisis_room.engine.clocks import clamp
from crisis_room.llm.task_contracts import AdvisorCouncilResponse, AdvisorDeltaProposal
from crisis_room.scenario.cuba import (
    CUBA_AIR_DEFENSE_ALERT_CAPABILITY_ID,
    CUBA_ANNOUNCE_NAVAL_QUARANTINE_CAPABILITY_ID,
    CUBA_OFFER_NON_INVASION_PLEDGE_CAPABILITY_ID,
    CUBA_OPEN_KREMLIN_CHANNEL_CAPABILITY_ID,
    CUBA_PREPARE_AIR_STRIKE_CAPABILITY_ID,
    CUBA_SECRET_JUPITER_TRADE_CAPABILITY_ID,
)
from crisis_room.state.advisors import (
    AdvisorBelief,
    AdvisorCouncilState,
    AdvisorCouncilUpdate,
    AdvisorState,
    AdvisorStateDelta,
)
from crisis_room.state.signals import SignalChannel
from crisis_room.state.world import WorldStateV2


def update_advisor_council(
    world_state: WorldStateV2,
    *,
    before_world_state: WorldStateV2,
    player_entity_id: str,
    action_catalog: list[ActionDefinition],
    capabilities: list[ScenarioCapability] | None = None,
    deterministic_result: DeterministicTurnResult,
    agent_outputs: dict[str, AgentOutput] | None = None,
    council_response: AdvisorCouncilResponse | None = None,
    event_output: AgentOutput | None = None,
    final_routing_result: RoutingResult | None = None,
) -> AdvisorCouncilUpdate | None:
    """Apply bounded, deterministic post-turn changes to persistent advisors."""

    council = world_state.advisor_councils.get(player_entity_id)
    if council is None:
        return None

    builder = _AdvisorUpdateBuilder(
        council,
        turn_number=world_state.turn_number,
        player_entity_id=player_entity_id,
    )
    resolver = ActionResolver(action_catalog, capabilities)

    _react_to_player_actions(builder, deterministic_result, resolver, player_entity_id)
    _react_to_rejections(builder, deterministic_result, resolver, player_entity_id)
    _react_to_metric_changes(builder, before_world_state, world_state)
    _react_to_npc_actions(builder, deterministic_result, resolver, player_entity_id)
    _react_to_agent_outputs(builder, agent_outputs or {}, player_entity_id)
    _react_to_council_response(builder, council_response)
    _react_to_event_pressure(builder, event_output, player_entity_id)
    _react_to_routing_noise(builder, final_routing_result, player_entity_id)

    update = builder.build_update()
    if update is None:
        return None

    _apply_update(council, update)
    world_state.advisor_update_history.append(update)
    if len(world_state.advisor_update_history) > MAX_ADVISOR_UPDATE_HISTORY:
        world_state.advisor_update_history = world_state.advisor_update_history[
            -MAX_ADVISOR_UPDATE_HISTORY:
        ]
    return update


class _AdvisorUpdateBuilder:
    def __init__(
        self,
        council: AdvisorCouncilState,
        *,
        turn_number: int,
        player_entity_id: str,
    ) -> None:
        self.council = council
        self.turn_number = turn_number
        self.player_entity_id = player_entity_id
        self.deltas: dict[str, AdvisorStateDelta] = {}

    def bump(
        self,
        advisor_id: str,
        *,
        reason: str,
        trust: float = 0.0,
        paranoia: float = 0.0,
        urgency: float = 0.0,
        confidence: float = 0.0,
        channel: SignalChannel | str | None = None,
        channel_trust: float = 0.0,
        belief_topic: str | None = None,
        belief_delta: float = 0.0,
        belief_summary: str = "",
        memory: str = "",
        recommendation: str = "",
        embarrassment: str = "",
    ) -> None:
        if advisor_id not in self.council.advisors:
            return
        delta = self.deltas.setdefault(
            advisor_id,
            AdvisorStateDelta(advisor_id=advisor_id),
        )
        delta.trust_player_delta += trust
        delta.paranoia_delta += paranoia
        delta.urgency_delta += urgency
        delta.institutional_confidence_delta += confidence
        if channel is not None and channel_trust:
            key = channel.value if isinstance(channel, SignalChannel) else str(channel)
            delta.trust_channel_deltas[key] = (
                delta.trust_channel_deltas.get(key, 0.0) + channel_trust
            )
        if belief_topic is not None and belief_delta:
            delta.belief_value_deltas[belief_topic] = (
                delta.belief_value_deltas.get(belief_topic, 0.0) + belief_delta
            )
        if belief_topic is not None and belief_summary:
            delta.belief_summaries[belief_topic] = belief_summary
        _append_unique(delta.reasons, reason)
        if memory:
            _append_unique(delta.memory_notes, memory)
        if recommendation:
            _append_unique(delta.recommendation_notes, recommendation)
        if embarrassment:
            _append_unique(delta.embarrassment_notes, embarrassment)

    def build_update(self) -> AdvisorCouncilUpdate | None:
        deltas = [
            _clamped_delta(delta)
            for delta in self.deltas.values()
            if _delta_has_content(delta)
        ]
        for delta in deltas:
            advisor = self.council.advisors[delta.advisor_id]
            delta.summary = _delta_summary(advisor, delta)
        summaries = [delta.summary for delta in deltas if delta.summary]
        if not deltas:
            return None
        return AdvisorCouncilUpdate(
            player_entity_id=self.player_entity_id,
            turn_number=self.turn_number,
            deltas=deltas,
            summary=summaries[:ADVISOR_SUMMARY_LIMIT],
        )


def _react_to_player_actions(
    builder: _AdvisorUpdateBuilder,
    deterministic_result: DeterministicTurnResult,
    resolver: ActionResolver,
    player_entity_id: str,
) -> None:
    packages = _unique_packages(
        [
            *deterministic_result.accepted_actions,
            *deterministic_result.scheduled_actions,
        ]
    )
    for package in packages:
        if package.actor_id != player_entity_id:
            continue
        definition = _resolve_definition(resolver, package)
        if definition is not None:
            _react_to_player_action(builder, package, definition)


def _react_to_player_action(
    builder: _AdvisorUpdateBuilder,
    package: ActionPackage,
    definition: ActionDefinition,
) -> None:
    title = definition.title
    channel = package.channel
    reason = f"player pursued {title}"

    if definition.category == ActionCategory.INTELLIGENCE:
        builder.bump(
            "intelligence",
            reason=reason,
            trust=0.04,
            urgency=0.02,
            paranoia=0.03,
            channel=channel,
            channel_trust=0.025,
            belief_topic="command_control",
            belief_delta=0.02,
            memory=f"Reconnaissance was prioritized through {title}.",
            recommendation="Keep intelligence collection paired with diplomatic control.",
        )

    if definition.category == ActionCategory.MILITARY:
        builder.bump(
            "defense",
            reason=reason,
            trust=0.035,
            urgency=0.025,
            channel=channel,
            channel_trust=0.02,
            memory=f"The player made military pressure credible with {title}.",
        )
        builder.bump(
            "intelligence",
            reason=reason,
            urgency=0.02,
            paranoia=0.02,
            recommendation="Watch for local command reactions to military pressure.",
        )
        builder.bump(
            "state",
            reason=reason,
            trust=-0.015,
            urgency=0.02,
            paranoia=0.015,
            recommendation="Preserve an off-ramp while pressure rises.",
        )
        builder.bump(
            "legal_un",
            reason=reason,
            trust=-0.02,
            urgency=0.02,
            recommendation="Anchor military pressure in visible legal legitimacy.",
        )

    if definition.category == ActionCategory.DIPLOMATIC:
        builder.bump(
            "state",
            reason=reason,
            trust=0.035,
            urgency=-0.02,
            paranoia=-0.015,
            channel=channel,
            channel_trust=0.025,
            belief_topic="face_saving",
            belief_delta=0.035,
            memory=f"The player kept diplomatic space open through {title}.",
        )
        builder.bump(
            "legal_un",
            reason=reason,
            trust=0.02,
            urgency=-0.01,
            confidence=0.01,
            channel=channel,
            channel_trust=0.015,
        )

    if definition.category == ActionCategory.INFORMATION or channel == SignalChannel.PUBLIC:
        builder.bump(
            "political",
            reason=reason,
            trust=0.025,
            urgency=0.02,
            channel=channel,
            channel_trust=0.02,
            memory=f"The public line hardened around {title}.",
        )

    capability_id = package.mechanical_id
    if capability_id == CUBA_ANNOUNCE_NAVAL_QUARANTINE_CAPABILITY_ID:
        builder.bump(
            "state",
            reason="quarantine preserved a bounded pressure path",
            trust=0.02,
            belief_topic="face_saving",
            belief_delta=0.015,
        )
        builder.bump(
            "legal_un",
            reason="quarantine needs legal framing",
            confidence=0.015,
            recommendation="Use OAS, UN, and careful language to distinguish quarantine from blockade.",
        )
    elif capability_id == CUBA_OPEN_KREMLIN_CHANNEL_CAPABILITY_ID:
        builder.bump(
            "state",
            reason="private Kremlin channel opened",
            trust=0.025,
            urgency=-0.015,
            channel=SignalChannel.BACKCHANNEL,
            channel_trust=0.035,
            belief_topic="face_saving",
            belief_delta=0.04,
            recommendation="Use the channel for concrete reciprocal terms before public pressure peaks.",
        )
    elif capability_id == CUBA_SECRET_JUPITER_TRADE_CAPABILITY_ID:
        builder.bump(
            "political",
            reason="secret Jupiter trade creates leak exposure",
            paranoia=0.035,
            urgency=0.015,
            embarrassment="A leaked Jupiter trade would be politically costly.",
        )
        builder.bump(
            "legal_un",
            reason="secret Jupiter trade complicates alliance legitimacy",
            trust=-0.015,
            paranoia=0.02,
        )
    elif capability_id == CUBA_PREPARE_AIR_STRIKE_CAPABILITY_ID:
        builder.bump(
            "defense",
            reason="air strike option prepared",
            trust=0.04,
            urgency=0.03,
            recommendation="Keep command authority explicit before any strike package matures.",
        )
        builder.bump(
            "state",
            reason="air strike preparation threatens diplomatic room",
            trust=-0.035,
            urgency=0.04,
            paranoia=0.03,
        )
    elif capability_id == CUBA_OFFER_NON_INVASION_PLEDGE_CAPABILITY_ID:
        builder.bump(
            "state",
            reason="non-invasion pledge supports a settlement path",
            trust=0.035,
            urgency=-0.02,
            belief_topic="face_saving",
            belief_delta=0.03,
        )
        builder.bump(
            "defense",
            reason="non-invasion pledge narrows coercive flexibility",
            trust=-0.01,
            urgency=0.01,
        )


def _react_to_rejections(
    builder: _AdvisorUpdateBuilder,
    deterministic_result: DeterministicTurnResult,
    resolver: ActionResolver,
    player_entity_id: str,
) -> None:
    for package in deterministic_result.rejected_actions:
        if package.actor_id != player_entity_id:
            continue
        definition = _resolve_definition(resolver, package)
        title = definition.title if definition is not None else package.mechanical_id
        validation = deterministic_result.validation_results.get(package.package_id)
        reason = "; ".join(validation.errors) if validation is not None else "failed validation"
        for advisor_id in builder.council.advisors:
            builder.bump(
                advisor_id,
                reason=f"player action rejected: {title}",
                trust=-0.025,
                urgency=0.015,
                embarrassment=f"{title} failed validation: {reason}",
            )


def _react_to_metric_changes(
    builder: _AdvisorUpdateBuilder,
    before: WorldStateV2,
    after: WorldStateV2,
) -> None:
    alarm = _change(before.public_metrics, after.public_metrics, "public_alarm")
    anxiety = _change(before.public_metrics, after.public_metrics, "market_anxiety")
    allied = _change(before.public_metrics, after.public_metrics, "allied_confidence")
    escalation = _change(before.hidden_clocks, after.hidden_clocks, "nuclear_escalation")
    command = _change(before.hidden_clocks, after.hidden_clocks, "command_and_control_risk")
    quarantine = _change(before.hidden_clocks, after.hidden_clocks, "quarantine_incident_risk")
    backchannel = _change(before.hidden_clocks, after.hidden_clocks, "backchannel_viability")

    public_pressure = alarm + anxiety
    if abs(public_pressure) >= ADVISOR_METRIC_CHANGE_THRESHOLD:
        builder.bump(
            "political",
            reason="public pressure changed",
            urgency=_scaled(public_pressure, 0.35),
            paranoia=_scaled(public_pressure, 0.22),
            belief_topic="public_alarm",
            belief_delta=_scaled(public_pressure, 0.3),
            memory=_direction_note("Public pressure", public_pressure),
        )
        builder.bump(
            "state",
            reason="public pressure changed",
            urgency=_scaled(public_pressure, 0.12),
        )

    if abs(allied) >= ADVISOR_METRIC_CHANGE_THRESHOLD:
        builder.bump(
            "state",
            reason="allied confidence changed",
            trust=_scaled(allied, 0.28),
            urgency=-_scaled(allied, 0.18),
            memory=_direction_note("Allied confidence", allied),
        )
        builder.bump(
            "legal_un",
            reason="allied confidence changed",
            trust=_scaled(allied, 0.24),
            confidence=_scaled(allied, 0.15),
            urgency=-_scaled(allied, 0.16),
            belief_topic="legitimacy",
            belief_delta=_scaled(allied, 0.22),
        )

    accident_pressure = escalation + command + quarantine
    if abs(accident_pressure) >= ADVISOR_METRIC_CHANGE_THRESHOLD:
        for advisor_id in ("defense", "intelligence"):
            builder.bump(
                advisor_id,
                reason="accident and escalation pressure changed",
                urgency=_scaled(accident_pressure, 0.24),
                paranoia=_scaled(accident_pressure, 0.2),
                memory=_direction_note("Accident pressure", accident_pressure),
            )
        builder.bump(
            "state",
            reason="accident and escalation pressure changed",
            urgency=_scaled(accident_pressure, 0.12),
            paranoia=_scaled(accident_pressure, 0.08),
        )

    if abs(backchannel) >= ADVISOR_METRIC_CHANGE_THRESHOLD:
        builder.bump(
            "state",
            reason="backchannel viability changed",
            trust=_scaled(backchannel, 0.32),
            urgency=-_scaled(backchannel, 0.22),
            paranoia=-_scaled(backchannel, 0.16),
            channel=SignalChannel.BACKCHANNEL,
            channel_trust=_scaled(backchannel, 0.28),
            belief_topic="face_saving",
            belief_delta=_scaled(backchannel, 0.24),
            memory=_direction_note("Backchannel viability", backchannel),
        )
        builder.bump(
            "political",
            reason="backchannel viability changed",
            paranoia=-_scaled(backchannel, 0.1),
        )


def _react_to_npc_actions(
    builder: _AdvisorUpdateBuilder,
    deterministic_result: DeterministicTurnResult,
    resolver: ActionResolver,
    player_entity_id: str,
) -> None:
    for package in deterministic_result.accepted_actions:
        if package.actor_id == player_entity_id:
            continue
        definition = _resolve_definition(resolver, package)
        title = definition.title if definition is not None else package.mechanical_id
        capability_id = package.mechanical_id
        if capability_id == "soviet_compromise_probe":
            builder.bump(
                "state",
                reason="Soviet probe suggests an off-ramp remains",
                trust=0.02,
                urgency=-0.02,
                channel=package.channel,
                channel_trust=0.02,
                belief_topic="face_saving",
                belief_delta=0.025,
                memory="Moscow tested compromise terms rather than only public defiance.",
            )
        elif capability_id == "soviet_defiance_statement":
            builder.bump(
                "political",
                reason="Soviet public defiance hardened public stakes",
                urgency=0.03,
                paranoia=0.025,
            )
            builder.bump("defense", reason="Soviet public defiance", urgency=0.025)
            builder.bump("state", reason="Soviet public defiance", trust=-0.015)
        elif capability_id == CUBA_AIR_DEFENSE_ALERT_CAPABILITY_ID:
            builder.bump(
                "intelligence",
                reason="Cuban air defense alert raises local control concern",
                urgency=0.035,
                paranoia=0.035,
                belief_topic="command_control",
                belief_delta=0.035,
                memory="Cuba raised air defense posture under crisis pressure.",
            )
            builder.bump(
                "defense",
                reason="Cuban air defense alert",
                urgency=0.03,
                paranoia=0.015,
            )
        elif capability_id == "nato_reassurance_pressure":
            for advisor_id in ("state", "political", "legal_un"):
                builder.bump(
                    advisor_id,
                    reason="NATO requested reassurance",
                    urgency=0.02,
                    recommendation="Consult allies before the next public move.",
                )
        elif definition is not None and definition.escalation_risk >= 0.4:
            builder.bump("defense", reason=f"NPC escalation via {title}", urgency=0.02)
            builder.bump(
                "intelligence",
                reason=f"NPC escalation via {title}",
                urgency=0.02,
                paranoia=0.02,
            )


def _react_to_agent_outputs(
    builder: _AdvisorUpdateBuilder,
    agent_outputs: dict[str, AgentOutput],
    player_entity_id: str,
) -> None:
    for entity_id, output in agent_outputs.items():
        if entity_id == player_entity_id or output.action_package is not None:
            continue
        if output.debug_notes:
            builder.bump(
                "intelligence",
                reason=f"{entity_id} submitted no valid action",
                paranoia=0.01,
                memory=f"{entity_id} produced no valid move: {output.debug_notes[0]}",
            )


def _react_to_council_response(
    builder: _AdvisorUpdateBuilder,
    council_response: AdvisorCouncilResponse | None,
) -> None:
    if council_response is None:
        return
    for proposal in council_response.proposed_advisor_deltas:
        _apply_delta_proposal(builder, proposal)


def _apply_delta_proposal(
    builder: _AdvisorUpdateBuilder,
    proposal: AdvisorDeltaProposal,
) -> None:
    if proposal.advisor_id not in builder.council.advisors:
        return
    reason = (
        "; ".join(proposal.reasons)
        if proposal.reasons
        else "advisor council response proposed a bounded update"
    )
    builder.bump(
        proposal.advisor_id,
        reason=reason,
        trust=proposal.trust_player_delta,
        paranoia=proposal.paranoia_delta,
        urgency=proposal.urgency_delta,
        confidence=proposal.institutional_confidence_delta,
    )
    for channel, delta in proposal.trust_channel_deltas.items():
        builder.bump(
            proposal.advisor_id,
            reason=reason,
            channel=channel,
            channel_trust=delta,
        )
    for topic, delta in proposal.belief_value_deltas.items():
        builder.bump(
            proposal.advisor_id,
            reason=reason,
            belief_topic=topic,
            belief_delta=delta,
            belief_summary=proposal.belief_summaries.get(topic, ""),
        )
    for topic, summary in proposal.belief_summaries.items():
        if topic not in proposal.belief_value_deltas:
            builder.bump(
                proposal.advisor_id,
                reason=reason,
                belief_topic=topic,
                belief_delta=0.0,
                belief_summary=summary,
            )
    for note in proposal.memory_notes:
        builder.bump(proposal.advisor_id, reason=reason, memory=note)
    for note in proposal.recommendation_notes:
        builder.bump(proposal.advisor_id, reason=reason, recommendation=note)
    for note in proposal.embarrassment_notes:
        builder.bump(proposal.advisor_id, reason=reason, embarrassment=note)


def _react_to_event_pressure(
    builder: _AdvisorUpdateBuilder,
    event_output: AgentOutput | None,
    player_entity_id: str,
) -> None:
    if event_output is None:
        return
    for signal in event_output.emitted_signals:
        if signal.recipient_entity_ids and player_entity_id not in signal.recipient_entity_ids:
            continue
        if signal.channel in {SignalChannel.INTEL, SignalChannel.MILITARY}:
            builder.bump(
                "intelligence",
                reason="event pressure reached the crisis room",
                urgency=0.02,
                paranoia=0.025,
                memory=event_output.perception_summary,
            )
        if signal.channel in {SignalChannel.MEDIA, SignalChannel.RUMOR, SignalChannel.PUBLIC}:
            builder.bump(
                "political",
                reason="public event pressure reached the crisis room",
                urgency=0.02,
                paranoia=0.02,
                memory=event_output.perception_summary,
            )


def _react_to_routing_noise(
    builder: _AdvisorUpdateBuilder,
    routing_result: RoutingResult | None,
    player_entity_id: str,
) -> None:
    if routing_result is None:
        return
    for signal in routing_result.leaked_signals:
        builder.bump(
            "political",
            reason="private signal leaked into public rumor",
            urgency=0.02,
            paranoia=0.03,
            channel=SignalChannel.BACKCHANNEL,
            channel_trust=-0.015,
            memory=f"A private signal leaked as public rumor: {signal.content}",
        )
        builder.bump(
            "state",
            reason="private signal leaked into public rumor",
            paranoia=0.02,
            channel=SignalChannel.BACKCHANNEL,
            channel_trust=-0.015,
        )
    for delivery in routing_result.deliveries:
        if delivery.recipient_entity_id != player_entity_id:
            continue
        if not delivery.distortion_applied and not delivery.contradiction_applied:
            continue
        builder.bump(
            "intelligence",
            reason="incoming report was distorted or contradicted",
            urgency=0.015,
            paranoia=0.025,
            channel=delivery.channel,
            channel_trust=-0.02,
            memory=f"Noisy {delivery.channel.value} report: {delivery.observed_content}",
        )


def _apply_update(
    council: AdvisorCouncilState,
    update: AdvisorCouncilUpdate,
) -> None:
    for delta in update.deltas:
        advisor = council.advisors.get(delta.advisor_id)
        if advisor is None:
            continue
        advisor.trust_player = _add_clamped(advisor.trust_player, delta.trust_player_delta)
        advisor.paranoia = _add_clamped(advisor.paranoia, delta.paranoia_delta)
        advisor.urgency = _add_clamped(advisor.urgency, delta.urgency_delta)
        advisor.institutional_confidence = _add_clamped(
            advisor.institutional_confidence,
            delta.institutional_confidence_delta,
        )
        for channel, channel_delta in delta.trust_channel_deltas.items():
            advisor.trust_channels[channel] = _add_clamped(
                advisor.trust_channels.get(channel, ADVISOR_BASE_CHANNEL_TRUST),
                channel_delta,
            )
        belief_topics = set(delta.belief_value_deltas) | set(delta.belief_summaries)
        for topic in belief_topics:
            belief_delta = delta.belief_value_deltas.get(topic, 0.0)
            belief = advisor.beliefs.get(topic) or AdvisorBelief(topic=topic)
            belief.value = _add_clamped(belief.value, belief_delta)
            if topic in delta.belief_value_deltas:
                belief.confidence = _add_clamped(
                    belief.confidence,
                    ADVISOR_BELIEF_CONFIDENCE_STEP,
                )
            belief.last_updated_turn = update.turn_number
            summary = delta.belief_summaries.get(topic)
            if summary:
                belief.summary = summary
            advisor.beliefs[topic] = belief
        if delta.memory_notes:
            advisor.memory_summary = _merge_memory_summary(
                advisor.memory_summary,
                delta.memory_notes,
            )
        advisor.recent_recommendations = _bounded_extend(
            advisor.recent_recommendations,
            delta.recommendation_notes,
        )
        advisor.recent_embarrassments = _bounded_extend(
            advisor.recent_embarrassments,
            delta.embarrassment_notes,
        )


def _unique_packages(packages: list[ActionPackage]) -> list[ActionPackage]:
    seen: set[str] = set()
    unique: list[ActionPackage] = []
    for package in packages:
        if package.package_id in seen:
            continue
        seen.add(package.package_id)
        unique.append(package)
    return unique


def _resolve_definition(
    resolver: ActionResolver,
    package: ActionPackage,
) -> ActionDefinition | None:
    definition, errors = resolver.resolve_package(package)
    return None if errors else definition


def _change(before: dict[str, float], after: dict[str, float], key: str) -> float:
    return float(after.get(key, 0.0)) - float(before.get(key, 0.0))


def _scaled(value: float, scale: float) -> float:
    return max(-ADVISOR_SCALE_CLAMP, min(ADVISOR_SCALE_CLAMP, value * scale))


def _direction_note(label: str, delta: float) -> str:
    direction = "rose" if delta > 0 else "fell"
    return f"{label} {direction} during the turn."


def _clamped_delta(delta: AdvisorStateDelta) -> AdvisorStateDelta:
    copy = delta.model_copy(deep=True)
    copy.trust_player_delta = _clamp_delta(copy.trust_player_delta)
    copy.paranoia_delta = _clamp_delta(copy.paranoia_delta)
    copy.urgency_delta = _clamp_delta(copy.urgency_delta)
    copy.institutional_confidence_delta = _clamp_delta(
        copy.institutional_confidence_delta
    )
    copy.trust_channel_deltas = {
        key: _clamp_delta(value) for key, value in copy.trust_channel_deltas.items()
    }
    copy.belief_value_deltas = {
        key: _clamp_delta(value) for key, value in copy.belief_value_deltas.items()
    }
    return copy


def _clamp_delta(value: float) -> float:
    return round(
        max(-ADVISOR_DELTA_CLAMP, min(ADVISOR_DELTA_CLAMP, value)),
        ADVISOR_DELTA_ROUND_DIGITS,
    )


def _add_clamped(value: float, delta: float) -> float:
    return round(clamp(float(value) + float(delta)), NUMERIC_ROUND_DIGITS)


def _delta_has_content(delta: AdvisorStateDelta) -> bool:
    numeric = [
        delta.trust_player_delta,
        delta.paranoia_delta,
        delta.urgency_delta,
        delta.institutional_confidence_delta,
        *delta.trust_channel_deltas.values(),
        *delta.belief_value_deltas.values(),
    ]
    return (
        any(abs(value) >= ADVISOR_VALUE_CHANGE_THRESHOLD for value in numeric)
        or bool(delta.belief_summaries)
        or bool(delta.memory_notes)
        or bool(delta.recommendation_notes)
        or bool(delta.embarrassment_notes)
    )


def _delta_summary(advisor: AdvisorState, delta: AdvisorStateDelta) -> str:
    pieces: list[str] = []
    if abs(delta.trust_player_delta) >= ADVISOR_SUMMARY_CHANGE_THRESHOLD:
        pieces.append(_moved("trust", delta.trust_player_delta))
    if abs(delta.urgency_delta) >= ADVISOR_SUMMARY_CHANGE_THRESHOLD:
        pieces.append(_moved("urgency", delta.urgency_delta))
    if abs(delta.paranoia_delta) >= ADVISOR_SUMMARY_CHANGE_THRESHOLD:
        pieces.append(_moved("paranoia", delta.paranoia_delta))
    if abs(delta.institutional_confidence_delta) >= ADVISOR_SUMMARY_CHANGE_THRESHOLD:
        pieces.append(
            _moved("institutional confidence", delta.institutional_confidence_delta)
        )
    if not pieces and delta.recommendation_notes:
        pieces.append(f"recommends {delta.recommendation_notes[-1]}")
    if not pieces and delta.memory_notes:
        pieces.append("updated memory")
    if not pieces:
        return ""
    return f"{advisor.name}: {', '.join(pieces)}."


def _moved(label: str, delta: float) -> str:
    direction = "up" if delta > 0 else "down"
    return f"{label} {direction}"


def _merge_memory_summary(existing: str, notes: list[str]) -> str:
    pieces = [piece.strip() for piece in existing.split(" | ") if piece.strip()]
    for note in notes:
        _append_unique(pieces, note)
    return " | ".join(pieces[-MAX_ADVISOR_RECENT_NOTES:])


def _bounded_extend(existing: list[str], notes: list[str]) -> list[str]:
    values = list(existing)
    for note in notes:
        _append_unique(values, note)
    return values[-MAX_ADVISOR_RECENT_NOTES:]


def _append_unique(values: list[str], value: str) -> None:
    cleaned = value.strip()
    if cleaned and cleaned not in values:
        values.append(cleaned)
