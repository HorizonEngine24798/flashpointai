from __future__ import annotations

from crisis_room.app.presentation import build_turn_briefing, render_turn_briefing
from crisis_room.app.turn_orchestrator import TurnOrchestrator
from crisis_room.llm.scripted_client import ScriptedLLMClient
from crisis_room.scenario.endings import (
    accept_ending_offer,
    evaluate_ending_events,
    reject_ending_offer,
    render_active_ending_offers,
)
from crisis_room.scenario.cuba import build_cuban_missile_crisis_1962_scenario
from crisis_room.state.events import ScenarioEventStatus
from crisis_room.state.world import WorldStateV2


def test_ending_evaluator_offers_scenario_ending_as_event_record() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=161)
    initial_briefing = render_turn_briefing(
        build_turn_briefing(
            world,
            player_entity_id=scenario.player_entity_id,
            action_catalog=scenario.action_catalog,
            capabilities=scenario.capabilities,
        )
    )
    world.truth_metrics["diplomatic_offramp"] = 0.84
    world.hidden_clocks["nuclear_escalation"] = 0.44
    world.active_commitments.append("settlement_framework_offered")

    evaluation = evaluate_ending_events(
        world,
        scenario.scenario_endings,
        player_entity_id=scenario.player_entity_id,
    )
    briefing = build_turn_briefing(
        evaluation.world_state,
        player_entity_id=scenario.player_entity_id,
        action_catalog=scenario.action_catalog,
        capabilities=scenario.capabilities,
    )

    assert "Ending available" not in initial_briefing
    assert evaluation.offer_record is not None
    assert evaluation.offer_record.ending_id == "settlement_reached"
    assert evaluation.event_record is not None
    assert evaluation.event_record.kind == "ending"
    assert evaluation.world_state.event_history[-1].metadata["ending_id"] == (
        "settlement_reached"
    )
    assert any(entry.metadata.get("ending_id") == "settlement_reached" for entry in evaluation.world_state.omniscient_timeline.entries)
    assert any(problem.source == "event" and "ACCEPT ENDING" in problem.summary for problem in briefing.problems)
    assert "Settlement Reached" in render_active_ending_offers(
        evaluation.world_state,
        player_entity_id=scenario.player_entity_id,
    )


def test_rejected_ending_uses_three_turn_reoffer_delay() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=162)
    world.truth_metrics["diplomatic_offramp"] = 0.84
    world.hidden_clocks["nuclear_escalation"] = 0.4
    world.active_commitments.append("settlement_framework_offered")
    offered = evaluate_ending_events(
        world,
        scenario.scenario_endings,
        player_entity_id=scenario.player_entity_id,
    )

    rejected = reject_ending_offer(
        offered.world_state,
        player_entity_id=scenario.player_entity_id,
    )
    delayed_world = rejected.world_state.model_copy(deep=True)
    delayed_world.turn_number = rejected.world_state.turn_number + 2
    delayed = evaluate_ending_events(
        delayed_world,
        scenario.scenario_endings,
        player_entity_id=scenario.player_entity_id,
    )
    eligible_world = rejected.world_state.model_copy(deep=True)

    assert rejected.rejected
    assert rejected.offer_record is not None
    assert rejected.offer_record.reoffer_after_turn == world.turn_number + 3
    assert rejected.world_state.event_history[-1].status == ScenarioEventStatus.EXPIRED
    assert delayed.offer_record is None
    assert any("reoffer delayed" in item for item in delayed.trace)
    assert rejected.offer_record.reoffer_after_turn is not None
    eligible_world.turn_number = rejected.offer_record.reoffer_after_turn
    reoffered = evaluate_ending_events(
        eligible_world,
        scenario.scenario_endings,
        player_entity_id=scenario.player_entity_id,
    )
    assert reoffered.offer_record is not None
    assert reoffered.offer_record.ending_id == "settlement_reached"


def test_settlement_requires_a_player_created_framework() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=1620)
    world.truth_metrics["diplomatic_offramp"] = 0.9
    world.hidden_clocks["nuclear_escalation"] = 0.3

    evaluation = evaluate_ending_events(
        world,
        scenario.scenario_endings,
        player_entity_id=scenario.player_entity_id,
    )

    assert evaluation.offer_record is None
    assert any(
        "settlement_reached: skipped (missing commitment" in item
        for item in evaluation.trace
    )


def test_accepting_ending_persists_final_timeline_summary() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=163)
    world.hidden_clocks["nuclear_escalation"] = 0.93
    offered = evaluate_ending_events(
        world,
        scenario.scenario_endings,
        player_entity_id=scenario.player_entity_id,
    )

    accepted = accept_ending_offer(
        offered.world_state,
        player_entity_id=scenario.player_entity_id,
    )
    rehydrated = WorldStateV2.model_validate_json(
        accepted.world_state.model_dump_json()
    )

    assert accepted.accepted
    assert accepted.world_state.accepted_ending_id == "nuclear_exchange"
    assert "Public timeline:" in accepted.world_state.final_summary
    assert "Classified timeline:" in accepted.world_state.final_summary
    assert "Unresolved issues:" in accepted.world_state.final_summary
    assert rehydrated.accepted_ending_offer_id == accepted.offer_record.offer_id


def test_turn_orchestrator_emits_ending_offer_after_resolution() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=164)
    world.hidden_clocks["nuclear_escalation"] = 0.93
    orchestrator = TurnOrchestrator(
        action_catalog=scenario.action_catalog,
        capabilities=scenario.capabilities,
        scenario_events=scenario.scenario_events,
        scenario_endings=scenario.scenario_endings,
        event_settings=scenario.event_settings,
        llm_client=ScriptedLLMClient(),
    )

    result = orchestrator.run_turn(
        world,
        player_entity_id=scenario.player_entity_id,
        player_intent="hold no action this turn",
        allow_empty_player_action=True,
    )

    assert result.ending_result is not None
    assert result.ending_result.offer_record is not None
    assert result.world_state.ending_offers[-1].ending_id == "nuclear_exchange"
    assert any(record.kind == "ending" for record in result.scenario_event_result.fired_events)
    assert "[endings]" in result.debug_transcript.rendered_text
