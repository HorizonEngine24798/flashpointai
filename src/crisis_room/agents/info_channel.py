from __future__ import annotations

import hashlib
from typing import Protocol

from pydantic import BaseModel, Field

from crisis_room.state.signals import (
    PayloadType,
    Signal,
    SignalChannel,
    SignalDelivery,
    SignalVisibility,
)
from crisis_room.state.timelines import TimelineEntry, TimelineScope
from crisis_room.state.world import WorldStateV2


class RoutingResult(BaseModel):
    world_state: WorldStateV2
    deliveries: list[SignalDelivery] = Field(default_factory=list)
    delayed_signals: list[Signal] = Field(default_factory=list)
    leaked_signals: list[Signal] = Field(default_factory=list)
    suppressed_signal_ids: list[str] = Field(default_factory=list)
    contradicted_delivery_ids: list[str] = Field(default_factory=list)
    public_timeline_entry_ids: list[str] = Field(default_factory=list)
    omniscient_timeline_entry_ids: list[str] = Field(default_factory=list)
    trace: list[str] = Field(default_factory=list)


class ChannelRule(BaseModel):
    channel: SignalChannel
    base_delay_turns: int = Field(default=0, ge=0)
    delay_risk: float = Field(default=0.0, ge=0.0, le=1.0)
    suppression_risk: float = Field(default=0.0, ge=0.0, le=1.0)
    distortion_multiplier: float = Field(default=1.0, ge=0.0)
    reliability_penalty_on_distortion: float = Field(default=0.25, ge=0.0, le=1.0)
    contradiction_risk: float = Field(default=0.0, ge=0.0, le=1.0)
    leak_multiplier: float = Field(default=1.0, ge=0.0)
    public_timeline_on_delivery: bool = True


class InfoChannelConfig(BaseModel):
    rules: dict[SignalChannel, ChannelRule] = Field(default_factory=dict)

    @classmethod
    def defaults(cls) -> InfoChannelConfig:
        return cls(
            rules={
                SignalChannel.PUBLIC: ChannelRule(channel=SignalChannel.PUBLIC),
                SignalChannel.MEDIA: ChannelRule(channel=SignalChannel.MEDIA),
                SignalChannel.RUMOR: ChannelRule(
                    channel=SignalChannel.RUMOR,
                    distortion_multiplier=0.8,
                    reliability_penalty_on_distortion=0.2,
                ),
                SignalChannel.BACKCHANNEL: ChannelRule(
                    channel=SignalChannel.BACKCHANNEL,
                    distortion_multiplier=1.0,
                    leak_multiplier=1.0,
                ),
                SignalChannel.PRIVATE_DIPLOMATIC: ChannelRule(
                    channel=SignalChannel.PRIVATE_DIPLOMATIC,
                    distortion_multiplier=1.0,
                    leak_multiplier=1.0,
                ),
                SignalChannel.INTEL: ChannelRule(
                    channel=SignalChannel.INTEL,
                    distortion_multiplier=1.15,
                    contradiction_risk=0.05,
                    public_timeline_on_delivery=False,
                ),
                SignalChannel.MILITARY: ChannelRule(
                    channel=SignalChannel.MILITARY,
                    distortion_multiplier=0.9,
                    public_timeline_on_delivery=False,
                ),
            }
        )

    def rule_for(self, channel: SignalChannel) -> ChannelRule:
        return self.rules.get(channel, ChannelRule(channel=channel))


class InfoChannel(Protocol):
    def route_signals(
        self,
        world_state: WorldStateV2,
        signals: list[Signal],
    ) -> RoutingResult:
        """Transform emitted signals into per-entity inbox deliveries."""


class PrototypeInfoChannel:
    """Deterministic fog-of-war router.

    Omniscient timelines receive the transformation audit. Public timelines
    receive only public or leaked/rumored observations. Entity-local timelines
    receive only delivery packets as perceived by that entity.
    """

    def __init__(self, config: InfoChannelConfig | None = None) -> None:
        self.config = config or InfoChannelConfig.defaults()

    def route_signals(
        self,
        world_state: WorldStateV2,
        signals: list[Signal],
    ) -> RoutingResult:
        next_world = world_state.model_copy(deep=True)
        result = RoutingResult(world_state=next_world)

        due_pending = self._collect_due_pending(next_world, result)
        for signal in [*due_pending, *signals]:
            next_world = self._route_one(next_world, result, signal)

        result.world_state = next_world
        return result

    def _route_one(
        self,
        world_state: WorldStateV2,
        result: RoutingResult,
        signal: Signal,
    ) -> WorldStateV2:
        result.trace.append(f"routing {signal.signal_id}")
        rule = self.config.rule_for(signal.channel)
        delayed = self._delay_if_needed(world_state, result, signal, rule)
        if delayed:
            return world_state

        if self._should_suppress(world_state, signal, rule):
            result.suppressed_signal_ids.append(signal.signal_id)
            self._append_omniscient_transform(
                world_state,
                result,
                signal,
                "Signal Suppressed",
                f"{signal.signal_id} was suppressed by the info channel.",
                suppressed=True,
            )
            result.trace.append(f"suppressed {signal.signal_id}")
            return world_state

        if signal.is_public and rule.public_timeline_on_delivery:
            entry = self._append_public_signal(world_state, signal)
            result.public_timeline_entry_ids.append(entry.entry_id)

        deliveries: list[SignalDelivery] = []
        for recipient_id in self._recipients(world_state, signal):
            delivery = self._deliver_to(world_state, signal, recipient_id, rule)
            world_state.deliver_to_entity(delivery)
            result.deliveries.append(delivery)
            deliveries.append(delivery)
            if delivery.contradiction_applied:
                result.contradicted_delivery_ids.append(delivery.delivery_id)
            result.trace.append(
                f"delivered {signal.signal_id} to {recipient_id}"
                + (" with contradiction" if delivery.contradiction_applied else "")
                + (" with distortion" if delivery.distortion_applied else "")
            )

        self._append_delivery_audit(world_state, result, signal, deliveries)

        leak = self._maybe_leak(world_state, signal, rule)
        if leak is not None:
            result.leaked_signals.append(leak)
            result.trace.append(f"leaked {signal.signal_id} as {leak.signal_id}")
            self._append_omniscient_transform(
                world_state,
                result,
                signal,
                "Signal Leaked",
                f"{signal.signal_id} leaked into public rumor as {leak.signal_id}.",
                leaked=True,
                leak_signal_id=leak.signal_id,
            )
            world_state = self._route_one(world_state, result, leak)
        return world_state

    def _collect_due_pending(
        self,
        world_state: WorldStateV2,
        result: RoutingResult,
    ) -> list[Signal]:
        due: list[Signal] = []
        remaining: list[Signal] = []
        for signal in world_state.pending_signals:
            if signal.intended_arrival_turn <= world_state.turn_number:
                due.append(signal)
                result.trace.append(f"pending signal due: {signal.signal_id}")
            else:
                remaining.append(signal)
        world_state.pending_signals = remaining
        return due

    def _recipients(self, world_state: WorldStateV2, signal: Signal) -> list[str]:
        if signal.is_public or not signal.recipient_entity_ids:
            return list(world_state.actors)
        return [
            recipient_id
            for recipient_id in signal.recipient_entity_ids
            if recipient_id in world_state.actors
        ]

    def _deliver_to(
        self,
        world_state: WorldStateV2,
        signal: Signal,
        recipient_id: str,
        rule: ChannelRule,
    ) -> SignalDelivery:
        contradiction = self._score(world_state, signal, recipient_id, "contradict")
        contradiction_risk = _metadata_float(
            signal,
            "contradiction_risk",
            rule.contradiction_risk,
        )
        contradictory = contradiction < contradiction_risk
        distortion = self._score(world_state, signal, recipient_id, "distort")
        distortion_risk = min(1.0, signal.distortion_risk * rule.distortion_multiplier)
        distorted = not contradictory and distortion < distortion_risk
        reliability = signal.reliability
        content = signal.content
        notes: list[str] = []
        if contradictory:
            reliability = max(0.0, signal.reliability - rule.reliability_penalty_on_distortion - 0.15)
            content = f"Contradictory report: sources dispute whether {signal.content}"
            notes.append("content contradicted by channel or source conflict")
        elif distorted:
            reliability = max(0.0, signal.reliability - rule.reliability_penalty_on_distortion)
            content = f"Distorted report: {signal.content}"
            notes.append("content distorted by channel risk")
        if signal.metadata.get("source_credibility_note"):
            notes.append(str(signal.metadata["source_credibility_note"]))

        return SignalDelivery(
            signal_id=signal.signal_id,
            recipient_entity_id=recipient_id,
            source_entity_id=signal.source_entity_id,
            arrived_turn=world_state.turn_number,
            channel=signal.channel,
            payload_type=signal.payload_type,
            observed_content=content,
            observed_reliability=reliability,
            visibility=signal.visibility,
            classification=signal.classification,
            distortion_applied=distorted,
            contradiction_applied=contradictory,
            leak_applied=bool(signal.metadata.get("leaked_from_signal_id")),
            delivery_notes=notes,
        )

    def _delay_if_needed(
        self,
        world_state: WorldStateV2,
        result: RoutingResult,
        signal: Signal,
        rule: ChannelRule,
    ) -> bool:
        already_delayed = bool(signal.metadata.get("info_channel_delay_applied"))
        delay_turns = 0 if already_delayed else rule.base_delay_turns
        if not already_delayed:
            delay_risk = _metadata_float(signal, "delay_risk", rule.delay_risk)
            if self._score(world_state, signal, "all", "delay") < delay_risk:
                delay_turns += 1
        intended_arrival = max(signal.intended_arrival_turn, world_state.turn_number + delay_turns)
        if intended_arrival <= world_state.turn_number:
            return False
        delayed_signal = signal.model_copy(deep=True)
        delayed_signal.intended_arrival_turn = intended_arrival
        delayed_signal.metadata["info_channel_delay_applied"] = True
        world_state.pending_signals.append(delayed_signal)
        result.delayed_signals.append(delayed_signal)
        self._append_omniscient_transform(
            world_state,
            result,
            signal,
            "Signal Delayed",
            f"{signal.signal_id} delayed until turn {intended_arrival}.",
            delayed_until=intended_arrival,
        )
        result.trace.append(f"delayed {signal.signal_id} until turn {intended_arrival}")
        return True

    def _should_suppress(
        self,
        world_state: WorldStateV2,
        signal: Signal,
        rule: ChannelRule,
    ) -> bool:
        risk = min(1.0, _metadata_float(signal, "suppression_risk", 0.0) + rule.suppression_risk)
        if risk <= 0.0:
            return False
        return self._score(world_state, signal, "all", "suppress") < risk

    def _maybe_leak(
        self,
        world_state: WorldStateV2,
        signal: Signal,
        rule: ChannelRule,
    ) -> Signal | None:
        if signal.is_public or signal.leak_risk <= 0.0:
            return None
        leak_risk = min(1.0, signal.leak_risk * rule.leak_multiplier)
        if self._score(world_state, signal, "public", "leak") >= leak_risk:
            return None
        leak_summary = str(
            signal.metadata.get(
                "leak_summary",
                f"Rumor circulating about undisclosed activity from {signal.source_entity_id}.",
            )
        )
        return Signal(
            signal_id=f"leak_{signal.signal_id}",
            source_entity_id="info_channel",
            recipient_entity_ids=[],
            channel=SignalChannel.RUMOR,
            payload_type=PayloadType.RUMOR,
            content=leak_summary,
            truth_reference_id=signal.truth_reference_id,
            emitted_turn=world_state.turn_number,
            intended_arrival_turn=world_state.turn_number,
            visibility=SignalVisibility.PUBLIC,
            reliability=max(0.1, signal.reliability - 0.4),
            deniability=1.0,
            leak_risk=0.0,
            distortion_risk=0.15,
            urgency=signal.urgency,
            classification="rumor",
            metadata={
                "leaked_from_signal_id": signal.signal_id,
                "info_channel_delay_applied": True,
            },
        )

    def _append_public_signal(self, world_state: WorldStateV2, signal: Signal) -> TimelineEntry:
        entry = TimelineEntry(
            entry_id=f"public_signal_{world_state.turn_number}_{signal.signal_id}",
            turn=world_state.turn_number,
            scope=TimelineScope.PUBLIC,
            title=_public_title(signal),
            summary=signal.content,
            source=signal.source_entity_id,
            signal_ids=[signal.signal_id],
            tags=["signal", signal.channel.value],
            metadata={
                "rumor": signal.payload_type == PayloadType.RUMOR,
                "leaked": bool(signal.metadata.get("leaked_from_signal_id")),
            },
        )
        world_state.public_timeline.append(entry)
        return entry

    def _append_delivery_audit(
        self,
        world_state: WorldStateV2,
        result: RoutingResult,
        signal: Signal,
        deliveries: list[SignalDelivery],
    ) -> None:
        recipients = ",".join(delivery.recipient_entity_id for delivery in deliveries)
        distorted = sum(1 for delivery in deliveries if delivery.distortion_applied)
        contradicted = sum(1 for delivery in deliveries if delivery.contradiction_applied)
        self._append_omniscient_transform(
            world_state,
            result,
            signal,
            "Signal Routed",
            f"{signal.signal_id} delivered to {recipients or 'no recipients'}.",
            delivery_count=len(deliveries),
            distorted_count=distorted,
            contradicted_count=contradicted,
        )

    def _append_omniscient_transform(
        self,
        world_state: WorldStateV2,
        result: RoutingResult,
        signal: Signal,
        title: str,
        summary: str,
        **metadata: str | int | float | bool,
    ) -> TimelineEntry:
        entry = TimelineEntry(
            entry_id=f"omn_info_{world_state.turn_number}_{signal.signal_id}_{_slug(title)}",
            turn=world_state.turn_number,
            scope=TimelineScope.OMNISCIENT,
            title=title,
            summary=summary,
            source="info_channel",
            signal_ids=[signal.signal_id],
            tags=["info_channel", signal.channel.value],
            metadata={
                "truth_reference_id": signal.truth_reference_id or "",
                **metadata,
            },
        )
        world_state.omniscient_timeline.append(entry)
        result.omniscient_timeline_entry_ids.append(entry.entry_id)
        return entry

    def _score(
        self,
        world_state: WorldStateV2,
        signal: Signal,
        recipient_id: str,
        purpose: str,
    ) -> float:
        material = (
            f"{world_state.rng_seed}:{world_state.turn_number}:"
            f"{signal.signal_id}:{recipient_id}:{purpose}"
        )
        digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
        return int(digest[:12], 16) / float(0xFFFFFFFFFFFF)


def _public_title(signal: Signal) -> str:
    if signal.payload_type == PayloadType.RUMOR:
        return "Rumor Circulates"
    if signal.channel == SignalChannel.MEDIA:
        return "Media Report"
    return "Public Signal"


def _metadata_float(signal: Signal, key: str, default: float) -> float:
    value = signal.metadata.get(key, default)
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, int | float):
        return float(value)
    return default


def _slug(value: str) -> str:
    return "_".join(value.lower().split())
