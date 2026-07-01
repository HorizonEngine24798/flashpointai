from __future__ import annotations

from crisis_room.app.presentation import render_aftermath_report
from crisis_room.app.turn_orchestrator import TurnOrchestrator
from crisis_room.llm.scripted_client import ScriptedLLMClient
from crisis_room.scenario.schema import build_cuban_missile_crisis_1962_scenario
from crisis_room.state.world import WorldStateV2


def test_advisor_update_loop_mutates_persistent_council_after_turn() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=61)
    initial_council = world.advisor_councils[scenario.player_entity_id].model_copy(
        deep=True
    )
    orchestrator = TurnOrchestrator(
        action_catalog=scenario.action_catalog,
        capabilities=scenario.capabilities,
        llm_client=ScriptedLLMClient(),
    )

    result = orchestrator.run_turn(
        world,
        player_entity_id=scenario.player_entity_id,
        player_intent="announce a naval quarantine and authorize recon overflights",
    )

    assert result.advisor_update is not None
    assert result.world_state.advisor_update_history[-1] == result.advisor_update
    council = result.world_state.advisor_councils[scenario.player_entity_id]
    assert (
        council.advisors["defense"].trust_player
        > initial_council.advisors["defense"].trust_player
    )
    assert (
        council.advisors["intelligence"].paranoia
        > initial_council.advisors["intelligence"].paranoia
    )
    assert council.advisors["state"].recent_recommendations
    assert "[advisor_updates]" in result.debug_transcript.rendered_text
    assert result.debug_transcript.advisor_update == result.advisor_update


def test_advisor_updates_surface_in_aftermath_and_survive_world_hydration() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=62)
    orchestrator = TurnOrchestrator(
        action_catalog=scenario.action_catalog,
        capabilities=scenario.capabilities,
        llm_client=ScriptedLLMClient(),
    )

    result = orchestrator.run_turn(
        world,
        player_entity_id=scenario.player_entity_id,
        player_intent="open a private Kremlin backchannel for reciprocal restraint",
    )
    rendered = render_aftermath_report(result.aftermath_report)
    rehydrated = WorldStateV2.model_validate(
        result.world_state.model_dump(mode="json")
    )

    assert "Council reaction:" in rendered
    assert any("State:" in line for line in result.aftermath_report.advisor_reactions)
    assert rehydrated.advisor_update_history
    assert rehydrated.advisor_update_history[-1].player_entity_id == scenario.player_entity_id
