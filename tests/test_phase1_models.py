from __future__ import annotations

from crisis_room.agents.info_channel import PrototypeInfoChannel
from crisis_room.scenario.cuba import build_cuban_missile_crisis_1962_scenario
from crisis_room.state.signals import (
    PayloadType,
    Signal,
    SignalChannel,
    SignalVisibility,
)
from crisis_room.state.world import WorldStateV2


def test_world_state_serializes_and_round_trips() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=123)

    payload = world.model_dump_json()
    restored = WorldStateV2.model_validate_json(payload)

    assert restored.schema_version == "world_state_v2"
    assert restored.scenario_id == "cuban_missile_crisis_1962"
    assert set(restored.actors) == {
        "us_excomm",
        "soviet_presidium",
        "cuba",
        "nato_allies",
        "international",
    }
    assert restored.public_timeline.entries[0].title == "Rumors Around Cuba Intensify"
    assert restored.entity_timelines["us_excomm"].owner_entity_id == "us_excomm"


def test_private_signal_reaches_only_intended_inbox() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=1)
    signal = Signal(
        signal_id="sig_private",
        source_entity_id="us_excomm",
        recipient_entity_ids=["soviet_presidium"],
        channel=SignalChannel.BACKCHANNEL,
        payload_type=PayloadType.BACKCHANNEL_MESSAGE,
        content="We are willing to discuss a reciprocal pause.",
        truth_reference_id="truth_hidden_1",
        emitted_turn=1,
        intended_arrival_turn=1,
        visibility=SignalVisibility.PRIVATE,
        reliability=0.9,
        leak_risk=0.0,
        distortion_risk=0.0,
        classification="secret",
    )

    result = PrototypeInfoChannel().route_signals(world, [signal])
    routed = result.world_state

    assert len(routed.actors["soviet_presidium"].inbox) == 1
    assert routed.actors["us_excomm"].inbox == []
    assert routed.actors["cuba"].inbox == []
    assert routed.actors["nato_allies"].inbox == []
    assert routed.actors["international"].inbox == []
    assert routed.public_timeline.entries == world.public_timeline.entries
    delivery = routed.actors["soviet_presidium"].inbox[0]
    assert delivery.observed_content == signal.content
    assert not hasattr(delivery, "truth_reference_id")


def test_signal_distortion_is_deterministic() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=42)
    signal = Signal(
        signal_id="sig_distorted",
        source_entity_id="us_excomm",
        recipient_entity_ids=["soviet_presidium"],
        channel=SignalChannel.INTEL,
        payload_type=PayloadType.INTEL_REPORT,
        content="Reconnaissance suggests a readiness change.",
        emitted_turn=1,
        intended_arrival_turn=1,
        visibility=SignalVisibility.SECRET,
        reliability=0.8,
        distortion_risk=1.0,
    )

    first = PrototypeInfoChannel().route_signals(world, [signal])
    second = PrototypeInfoChannel().route_signals(world, [signal])

    first_delivery = first.world_state.actors["soviet_presidium"].inbox[0]
    second_delivery = second.world_state.actors["soviet_presidium"].inbox[0]
    assert first_delivery.distortion_applied
    assert second_delivery.distortion_applied
    assert first_delivery.observed_content == second_delivery.observed_content
    assert first_delivery.observed_content.startswith("Distorted report:")


def test_public_and_omniscient_timelines_stay_separate_for_private_signal() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=5)
    initial_public_entries = list(world.public_timeline.entries)
    signal = Signal(
        signal_id="sig_secret",
        source_entity_id="us_excomm",
        recipient_entity_ids=["soviet_presidium"],
        channel=SignalChannel.PRIVATE_DIPLOMATIC,
        payload_type=PayloadType.PRIVATE_DIPLOMATIC_MESSAGE,
        content="A private offer exists.",
        truth_reference_id="secret_offer",
        emitted_turn=1,
        intended_arrival_turn=1,
        visibility=SignalVisibility.PRIVATE,
        leak_risk=0.0,
        distortion_risk=0.0,
    )

    routed = PrototypeInfoChannel().route_signals(world, [signal]).world_state

    assert routed.public_timeline.entries == initial_public_entries
    assert routed.entity_timelines["soviet_presidium"].entries[-1].summary == (
        "A private offer exists."
    )
    assert "secret_offer" not in routed.entity_timelines["soviet_presidium"].entries[-1].summary
