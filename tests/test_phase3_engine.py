from __future__ import annotations

from crisis_room.engine import ActionPackage, DeterministicEngineV2
from crisis_room.engine.actions import ActionCategory, ActionDefinition
from crisis_room.scenario.schema import build_cuban_missile_crisis_1962_scenario
from crisis_room.state.signals import PayloadType, SignalChannel, SignalVisibility


def test_engine_v2_rejects_invalid_channel_and_insufficient_resources() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=7)
    engine = DeterministicEngineV2(scenario.action_catalog)

    bad_channel = ActionPackage(
        package_id="pkg_bad_channel",
        actor_id="us_excomm",
        action_id="private_kremlin_backchannel",
        target_ids=["soviet_presidium"],
        channel=SignalChannel.PUBLIC,
        intent_summary="Try to quietly open a public backchannel contradiction.",
    )
    validation = engine.validate_action(world, bad_channel)
    assert not validation.is_valid
    assert any("channel public not allowed" in error for error in validation.errors)

    world.actors["us_excomm"].resources["political_capital"] = 0
    no_resources = bad_channel.model_copy(update={"channel": SignalChannel.BACKCHANNEL})
    validation = engine.validate_action(world, no_resources)
    assert not validation.is_valid
    assert any("insufficient resources" in error for error in validation.errors)


def test_engine_v2_resolves_private_kremlin_backchannel_effects_and_signal() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=11)
    engine = DeterministicEngineV2(scenario.action_catalog)
    action = ActionPackage(
        package_id="pkg_backchannel",
        actor_id="us_excomm",
        action_id="private_kremlin_backchannel",
        target_ids=["soviet_presidium"],
        channel=SignalChannel.BACKCHANNEL,
        intent_summary="Open a quiet channel for a reciprocal pause.",
        private_rationale="Reduce escalation without forcing public concessions.",
    )

    result = engine.resolve_actions(world, [action])
    resolved = result.world_state

    assert len(result.accepted_actions) == 1
    assert not result.rejected_actions
    assert resolved.actors["us_excomm"].resources["political_capital"] == 6
    assert resolved.truth_metrics["escalation_pressure"] == 0.38
    assert resolved.hidden_clocks["nuclear_escalation"] == 0.31
    assert resolved.hidden_clocks["backchannel_viability"] == 0.64
    assert resolved.relationships["us_excomm->soviet_presidium"]["trust"] == 0.1
    assert len(result.emitted_signals) == 1
    signal = result.emitted_signals[0]
    assert signal.signal_id == "sig_1_pkg_backchannel_private_kremlin_backchannel"
    assert signal.recipient_entity_ids == ["soviet_presidium"]
    assert signal.payload_type == PayloadType.BACKCHANNEL_MESSAGE
    assert signal.visibility == SignalVisibility.COVERT
    assert len(resolved.public_timeline.entries) == 1
    assert resolved.omniscient_timeline.entries[-1].entry_id == "omn_1_pkg_backchannel_executed"
    assert result.causal_trace


def test_engine_v2_public_action_writes_public_timeline() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=12)
    engine = DeterministicEngineV2(scenario.action_catalog)
    action = ActionPackage(
        package_id="pkg_public",
        actor_id="us_excomm",
        action_id="public_demand_withdrawal",
        target_ids=["soviet_presidium"],
        channel=SignalChannel.PUBLIC,
        intent_summary="Warn publicly against further deployments.",
        public_rationale="Further deployments will carry serious consequences.",
    )

    result = engine.resolve_actions(world, [action])
    resolved = result.world_state

    assert len(resolved.public_timeline.entries) == 2
    assert resolved.public_timeline.entries[-1].title == "U.S. Public Demand"
    assert resolved.public_timeline.entries[-1].summary == (
        "Further deployments will carry serious consequences."
    )
    assert result.emitted_signals[0].recipient_entity_ids == []
    assert result.emitted_signals[0].visibility == SignalVisibility.PUBLIC
    assert resolved.public_metrics["public_alarm"] == 0.42


def test_engine_v2_schedules_and_completes_prepared_action_without_double_cost() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=13)
    engine = DeterministicEngineV2(scenario.action_catalog)
    action = ActionPackage(
        package_id="pkg_prepare",
        actor_id="us_excomm",
        action_id="announce_quarantine",
        target_ids=["soviet_presidium", "cuba"],
        channel=SignalChannel.PUBLIC,
        intent_summary="Announce and prepare a naval quarantine posture.",
    )

    scheduled_result = engine.resolve_actions(world, [action])
    scheduled_world = scheduled_result.world_state

    assert scheduled_result.accepted_actions == []
    assert len(scheduled_result.scheduled_actions) == 1
    assert scheduled_world.actors["us_excomm"].resources["political_capital"] == 6
    assert scheduled_world.actors["us_excomm"].resources["alliance_credit"] == 2
    assert scheduled_world.actors["us_excomm"].resources["military_readiness"] == 5
    assert scheduled_world.pending_actions[0].metadata["ready_turn"] == 2

    scheduled_world.turn_number = 2
    completed_result = engine.resolve_actions(scheduled_world, [])
    completed_world = completed_result.world_state

    assert len(completed_result.completed_pending_actions) == 1
    assert len(completed_result.accepted_actions) == 1
    assert completed_world.pending_actions == []
    assert completed_world.actors["us_excomm"].resources["political_capital"] == 6
    assert completed_world.actors["us_excomm"].resources["alliance_credit"] == 2
    assert completed_world.actors["us_excomm"].resources["military_readiness"] == 4
    assert completed_world.truth_metrics["escalation_pressure"] == 0.54
    assert completed_world.hidden_clocks["nuclear_escalation"] == 0.42
    assert completed_world.hidden_clocks["quarantine_incident_risk"] == 0.36
    assert completed_result.emitted_signals[0].signal_id == (
        "sig_2_pkg_prepare_announce_quarantine"
    )


def test_engine_v2_cooldown_blocks_repeat_action_until_ready() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=14)
    engine = DeterministicEngineV2(scenario.action_catalog)
    action = ActionPackage(
        package_id="pkg_prepare",
        actor_id="us_excomm",
        action_id="announce_quarantine",
        target_ids=["soviet_presidium", "cuba"],
        channel=SignalChannel.PUBLIC,
        intent_summary="Announce and prepare a naval quarantine posture.",
    )
    scheduled_world = engine.resolve_actions(world, [action]).world_state
    scheduled_world.turn_number = 2

    repeat = action.model_copy(update={"package_id": "pkg_repeat"})
    validation = engine.validate_action(scheduled_world, repeat)

    assert not validation.is_valid
    assert any("cooldown until turn 3" in error for error in validation.errors)


def test_engine_v2_preconditions_use_metrics_and_clocks() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=15)
    definition = ActionDefinition(
        action_id="stabilization_offer",
        title="Stabilization Offer",
        category=ActionCategory.DIPLOMATIC,
        actor_types_allowed=["player_faction"],
        targets_allowed=["opposing_faction"],
        channels_allowed=[SignalChannel.PRIVATE_DIPLOMATIC],
        min_targets=1,
        preconditions=["public:public_alarm>=0.5", "clock:accidental_escalation<0.5"],
    )
    engine = DeterministicEngineV2([definition])
    action = ActionPackage(
        package_id="pkg_precondition",
        actor_id="us_excomm",
        action_id="stabilization_offer",
        target_ids=["soviet_presidium"],
        channel=SignalChannel.PRIVATE_DIPLOMATIC,
        intent_summary="Offer mutual stabilization measures.",
    )

    assert not engine.validate_action(world, action).is_valid
    world.public_metrics["public_alarm"] = 0.5
    assert engine.validate_action(world, action).is_valid


def test_engine_v2_replay_is_deterministic_for_same_world_and_actions() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=16)
    action = ActionPackage(
        package_id="pkg_replay",
        actor_id="us_excomm",
        action_id="private_kremlin_backchannel",
        target_ids=["soviet_presidium"],
        channel=SignalChannel.BACKCHANNEL,
        intent_summary="Open a quiet channel for replay verification.",
    )
    engine = DeterministicEngineV2(scenario.action_catalog)

    first = engine.resolve_actions(world, [action])
    second = engine.resolve_actions(world, [action])

    assert first.world_state.model_dump(mode="json") == second.world_state.model_dump(
        mode="json"
    )
    assert [entry.model_dump(mode="json") for entry in first.causal_trace] == [
        entry.model_dump(mode="json") for entry in second.causal_trace
    ]
