from __future__ import annotations

from crisis_room.app.presentation import (
    build_turn_briefing,
    render_aftermath_report,
)
from crisis_room.app.turn_orchestrator import TurnOrchestrator
from crisis_room.engine.actions import ActionPackage
from crisis_room.engine.adjudication import DeterministicEngineV2
from crisis_room.llm.scripted_client import ScriptedLLMClient
from crisis_room.scenario.events import resolve_scenario_events
from crisis_room.scenario.cuba import build_cuban_missile_crisis_1962_scenario
from crisis_room.state.signals import SignalChannel
from crisis_room.state.world import WorldStateV2


def test_scenario_event_resolver_applies_authored_effects_and_history() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=101)
    engine = DeterministicEngineV2(scenario.action_catalog, scenario.capabilities)
    deterministic_result = engine.resolve_actions(
        world,
        [
            ActionPackage(
                actor_id=scenario.player_entity_id,
                action_id="military_posture",
                capability_id="cuba_announce_naval_quarantine",
                target_ids=["soviet_presidium", "cuba"],
                channel=SignalChannel.PUBLIC,
                intent_summary="Announce and prepare a naval quarantine.",
                public_rationale="Further offensive shipments to Cuba will be stopped.",
                submitted_turn=world.turn_number,
            )
        ],
    )

    resolution = resolve_scenario_events(
        deterministic_result.world_state,
        scenario.scenario_events,
        deterministic_result=deterministic_result,
        player_entity_id=scenario.player_entity_id,
        framing_summary="LLM framing is available but non-authoritative.",
    )
    rehydrated = WorldStateV2.model_validate_json(
        resolution.world_state.model_dump_json()
    )

    assert [record.event_id for record in resolution.fired_events] == [
        "quarantine_contact_warning"
    ]
    assert resolution.emitted_signals[0].metadata["scenario_event_id"] == (
        "quarantine_contact_warning"
    )
    assert (
        resolution.world_state.public_metrics["public_alarm"]
        > deterministic_result.world_state.public_metrics["public_alarm"]
    )
    assert resolution.world_state.event_history[0].active_for(
        world.turn_number,
        scenario.player_entity_id,
    )
    assert rehydrated.event_history[0].event_id == "quarantine_contact_warning"


def test_scenario_events_fire_inside_orchestrated_turn_and_surface_to_player() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=102)
    orchestrator = TurnOrchestrator(
        action_catalog=scenario.action_catalog,
        capabilities=scenario.capabilities,
        scenario_events=scenario.scenario_events,
        llm_client=ScriptedLLMClient(),
    )

    result = orchestrator.run_turn(
        world,
        player_entity_id=scenario.player_entity_id,
        player_intent="authorize reconnaissance overflights",
    )
    rendered = render_aftermath_report(result.aftermath_report)
    briefing = build_turn_briefing(
        result.world_state,
        player_entity_id=scenario.player_entity_id,
        action_catalog=scenario.action_catalog,
        capabilities=scenario.capabilities,
    )

    assert result.scenario_event_result is not None
    assert [record.event_id for record in result.scenario_event_result.fired_events] == [
        "recon_air_defense_scare"
    ]
    assert "Flash events:" in rendered
    assert "Reconnaissance Air-Defense Scare" in rendered
    assert "command_and_control_risk" not in rendered
    assert any(problem.source == "event" for problem in briefing.problems)
    assert "[scenario_events]" in result.debug_transcript.rendered_text
    assert "recon_air_defense_scare" in result.debug_transcript.rendered_text


def test_scenario_event_once_gate_prevents_repeat_fire() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=103)
    engine = DeterministicEngineV2(scenario.action_catalog, scenario.capabilities)
    package = ActionPackage(
        actor_id=scenario.player_entity_id,
        action_id="military_posture",
        capability_id="cuba_announce_naval_quarantine",
        target_ids=["soviet_presidium", "cuba"],
        channel=SignalChannel.PUBLIC,
        intent_summary="Announce and prepare a naval quarantine.",
        public_rationale="Further offensive shipments to Cuba will be stopped.",
        submitted_turn=world.turn_number,
    )
    deterministic_result = engine.resolve_actions(world, [package])
    first = resolve_scenario_events(
        deterministic_result.world_state,
        scenario.scenario_events,
        deterministic_result=deterministic_result,
        player_entity_id=scenario.player_entity_id,
    )

    second = resolve_scenario_events(
        first.world_state,
        scenario.scenario_events,
        deterministic_result=deterministic_result,
        player_entity_id=scenario.player_entity_id,
    )

    assert len(first.fired_events) == 1
    assert second.fired_events == []
    assert second.no_event_reason == "no authored scenario event fired"
    assert any("quarantine_contact_warning: skipped (already fired)" in item for item in second.trace)
