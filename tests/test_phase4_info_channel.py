from __future__ import annotations

from crisis_room.agents.info_channel import ChannelRule, InfoChannelConfig, PrototypeInfoChannel
from crisis_room.llm.contracts import FakeLLMClient
from crisis_room.scenario.cuba import build_cuban_missile_crisis_1962_scenario
from crisis_room.state.signals import (
    PayloadType,
    Signal,
    SignalChannel,
    SignalVisibility,
)


def test_info_channel_delays_pending_signal_then_delivers_when_due() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=21)
    channel = PrototypeInfoChannel(
        InfoChannelConfig(
            rules={
                SignalChannel.BACKCHANNEL: ChannelRule(
                    channel=SignalChannel.BACKCHANNEL,
                    base_delay_turns=1,
                )
            }
        )
    )
    signal = _signal(
        signal_id="sig_delay",
        channel=SignalChannel.BACKCHANNEL,
        payload_type=PayloadType.BACKCHANNEL_MESSAGE,
        visibility=SignalVisibility.COVERT,
        recipient_entity_ids=["soviet_presidium"],
    )

    delayed = channel.route_signals(world, [signal])

    assert delayed.deliveries == []
    assert len(delayed.delayed_signals) == 1
    assert delayed.world_state.pending_signals[0].intended_arrival_turn == 2
    assert delayed.world_state.omniscient_timeline.entries[-1].title == "Signal Delayed"

    due_world = delayed.world_state
    due_world.turn_number = 2
    delivered = channel.route_signals(due_world, [])

    assert len(delivered.deliveries) == 1
    assert delivered.deliveries[0].recipient_entity_id == "soviet_presidium"
    assert delivered.world_state.pending_signals == []
    assert delivered.world_state.entity_timelines["soviet_presidium"].entries[-1].summary == signal.content


def test_info_channel_leak_creates_public_rumor_without_truth_reference_or_secret_content() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=22)
    signal = _signal(
        signal_id="sig_leak",
        content="Secret concession package codename BLUE LANTERN.",
        truth_reference_id="truth_secret_blue_lantern",
        channel=SignalChannel.PRIVATE_DIPLOMATIC,
        payload_type=PayloadType.PRIVATE_DIPLOMATIC_MESSAGE,
        visibility=SignalVisibility.PRIVATE,
        recipient_entity_ids=["soviet_presidium"],
        leak_risk=1.0,
        metadata={"leak_summary": "Rumor circulating about a possible private offer."},
    )

    result = PrototypeInfoChannel().route_signals(world, [signal])
    routed = result.world_state

    assert len(result.leaked_signals) == 1
    assert result.leaked_signals[0].content == "Rumor circulating about a possible private offer."
    assert "BLUE LANTERN" not in routed.public_timeline.entries[-1].summary
    assert "truth_secret_blue_lantern" not in routed.public_timeline.entries[-1].model_dump_json()
    assert "truth_secret_blue_lantern" not in routed.entity_timelines["soviet_presidium"].model_dump_json()
    assert "truth_secret_blue_lantern" in routed.omniscient_timeline.model_dump_json()


def test_info_channel_suppresses_signal_without_delivery_or_public_entry() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=23)
    initial_public_count = len(world.public_timeline.entries)
    signal = _signal(
        signal_id="sig_suppress",
        channel=SignalChannel.INTEL,
        payload_type=PayloadType.INTEL_REPORT,
        visibility=SignalVisibility.SECRET,
        recipient_entity_ids=["us_excomm"],
        metadata={"suppression_risk": 1.0},
    )

    result = PrototypeInfoChannel().route_signals(world, [signal])

    assert result.deliveries == []
    assert result.suppressed_signal_ids == ["sig_suppress"]
    assert len(result.world_state.public_timeline.entries) == initial_public_count
    assert result.world_state.omniscient_timeline.entries[-1].title == "Signal Suppressed"


def test_info_channel_contradictory_delivery_is_entity_local_only() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=24)
    signal = _signal(
        signal_id="sig_contra",
        channel=SignalChannel.INTEL,
        payload_type=PayloadType.INTEL_REPORT,
        visibility=SignalVisibility.SECRET,
        recipient_entity_ids=["us_excomm"],
        metadata={"contradiction_risk": 1.0},
    )

    result = PrototypeInfoChannel().route_signals(world, [signal])
    delivery = result.deliveries[0]

    assert delivery.contradiction_applied
    assert delivery.observed_content.startswith("Contradictory report:")
    assert delivery.delivery_id in result.contradicted_delivery_ids
    assert result.world_state.entity_timelines["us_excomm"].entries[-1].metadata["contradictory"]
    assert result.world_state.public_timeline.entries == world.public_timeline.entries


def test_llm_distortion_rewrites_public_signal_before_timeline_and_delivery() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=240)
    distorted_text = "Reports suggest Washington may be hinting at restraint, but terms are unclear."
    fake_llm = FakeLLMClient(
        {
            "info_channel.sig_public_distorted.distorted": {
                "observed_content": distorted_text,
                "distortion_note": "Specific non-invasion terms were blurred.",
            }
        }
    )
    signal = _signal(
        signal_id="sig_public_distorted",
        content="Washington publicly promises no invasion if missiles are removed.",
        channel=SignalChannel.PUBLIC,
        payload_type=PayloadType.PUBLIC_STATEMENT,
        visibility=SignalVisibility.PUBLIC,
        distortion_risk=1.0,
    )

    result = PrototypeInfoChannel(llm_client=fake_llm).route_signals(world, [signal])
    routed = result.world_state

    assert routed.public_timeline.entries[-1].summary == distorted_text
    assert {delivery.observed_content for delivery in result.deliveries} == {distorted_text}
    assert all(delivery.distortion_applied for delivery in result.deliveries)
    assert all(delivery.observed_reliability == 0.65 for delivery in result.deliveries)
    assert fake_llm.calls[0].request.response_schema_name == "SignalDistortionResponse"


def test_info_channel_public_signal_reaches_all_entities_and_public_timeline() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=25)
    signal = _signal(
        signal_id="sig_public",
        content="A public warning is broadcast.",
        channel=SignalChannel.PUBLIC,
        payload_type=PayloadType.PUBLIC_STATEMENT,
        visibility=SignalVisibility.PUBLIC,
        recipient_entity_ids=[],
    )

    result = PrototypeInfoChannel().route_signals(world, [signal])
    routed = result.world_state

    assert {delivery.recipient_entity_id for delivery in result.deliveries} == {
        "us_excomm",
        "soviet_presidium",
        "cuba",
        "nato_allies",
        "international",
    }
    assert routed.public_timeline.entries[-1].entry_id == "public_signal_1_sig_public"
    assert routed.public_timeline.entries[-1].summary == "A public warning is broadcast."
    assert all(entity.inbox for entity in routed.actors.values())


def test_info_channel_entity_delivery_does_not_expose_omniscient_truth_fields() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=26)
    signal = _signal(
        signal_id="sig_hidden_truth",
        truth_reference_id="truth_hidden_anchor",
        channel=SignalChannel.BACKCHANNEL,
        payload_type=PayloadType.BACKCHANNEL_MESSAGE,
        visibility=SignalVisibility.COVERT,
        recipient_entity_ids=["soviet_presidium"],
    )

    result = PrototypeInfoChannel().route_signals(world, [signal])
    routed = result.world_state

    delivery_json = result.deliveries[0].model_dump_json()
    entity_timeline_json = routed.entity_timelines["soviet_presidium"].model_dump_json()
    public_json = routed.public_timeline.model_dump_json()

    assert "truth_hidden_anchor" not in delivery_json
    assert "truth_hidden_anchor" not in entity_timeline_json
    assert "truth_hidden_anchor" not in public_json
    assert "truth_hidden_anchor" in routed.omniscient_timeline.model_dump_json()


def _signal(
    *,
    signal_id: str,
    content: str = "A sensitive report is moving through a contested channel.",
    source_entity_id: str = "us_excomm",
    recipient_entity_ids: list[str] | None = None,
    channel: SignalChannel = SignalChannel.PRIVATE_DIPLOMATIC,
    payload_type: PayloadType = PayloadType.PRIVATE_DIPLOMATIC_MESSAGE,
    visibility: SignalVisibility = SignalVisibility.PRIVATE,
    truth_reference_id: str | None = None,
    leak_risk: float = 0.0,
    distortion_risk: float = 0.0,
    metadata: dict[str, str | int | float | bool] | None = None,
) -> Signal:
    return Signal(
        signal_id=signal_id,
        source_entity_id=source_entity_id,
        recipient_entity_ids=recipient_entity_ids or [],
        channel=channel,
        payload_type=payload_type,
        content=content,
        truth_reference_id=truth_reference_id,
        emitted_turn=1,
        intended_arrival_turn=1,
        visibility=visibility,
        reliability=0.9,
        leak_risk=leak_risk,
        distortion_risk=distortion_risk,
        classification="secret" if visibility != SignalVisibility.PUBLIC else "public",
        metadata=metadata or {},
    )
