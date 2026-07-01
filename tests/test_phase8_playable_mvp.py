from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from crisis_room.agents.dialogue_engine import DialogueEngineAgent
from crisis_room.app.debug_sessions import DebugSessionRecorder, load_debug_session
from crisis_room.app.presentation import (
    build_turn_briefing,
    render_aftermath_report,
    render_turn_briefing,
)
from crisis_room.app.turn_orchestrator import TurnOrchestrator
from crisis_room.app.tui import _format_runtime_error
from crisis_room.llm.diagnostics import LlamaCppJSONError
from crisis_room.llm.scripted_client import ScriptedLLMClient
from crisis_room.scenario.schema import build_cuban_missile_crisis_1962_scenario


def test_scripted_client_makes_cuba_scenario_playable_without_live_llm() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=41)
    client = ScriptedLLMClient()
    orchestrator = TurnOrchestrator(
        action_catalog=scenario.action_catalog,
        capabilities=scenario.capabilities,
        llm_client=client,
    )

    first = orchestrator.run_turn(
        world,
        player_entity_id=scenario.player_entity_id,
        player_intent="issue a public warning demanding missile withdrawal",
    )
    second = orchestrator.run_turn(
        first.world_state,
        player_entity_id=scenario.player_entity_id,
        player_intent="open a private Kremlin backchannel for reciprocal restraint",
    )

    assert first.world_state.turn_number == 2
    assert second.world_state.turn_number == 3
    assert {
        action.mechanical_id for action in first.deterministic_result.accepted_actions
    } == {
        "cuba_public_withdrawal_demand",
        "soviet_compromise_probe",
        "cuba_air_defense_alert",
        "nato_reassurance_pressure",
    }
    assert {
        action.mechanical_id for action in second.deterministic_result.accepted_actions
    } == {
        "cuba_open_kremlin_channel",
        "soviet_compromise_probe",
        "cuba_air_defense_alert",
        "nato_reassurance_pressure",
    }
    assert len(first.debug_transcript.llm_calls) == 6
    assert len(second.debug_transcript.llm_calls) == 6
    assert second.world_state.actors["us_excomm"].inbox

    recorder = DebugSessionRecorder(
        world_state=world,
        player_entity_id=scenario.player_entity_id,
        output_dir=_test_output_dir("turns"),
    )
    recorder.append_turn(first.debug_transcript, first.world_state)
    recorder.append_turn(second.debug_transcript, second.world_state)
    path = recorder.save()
    loaded = load_debug_session(path)

    assert loaded.scenario_id == scenario.scenario_id
    assert loaded.world_state.turn_number == 3
    assert len(loaded.turn_transcripts) == 2
    assert "ORCHESTRATED TURN DEBUG" in loaded.rendered_log[-1]


def test_multi_action_player_turn_compiles_and_resolves_as_agenda_batch() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=43)
    orchestrator = TurnOrchestrator(
        action_catalog=scenario.action_catalog,
        capabilities=scenario.capabilities,
        llm_client=ScriptedLLMClient(),
    )

    result = orchestrator.run_turn(
        world,
        player_entity_id=scenario.player_entity_id,
        player_intent=(
            "announce a naval quarantine, keep a private Kremlin backchannel open, "
            "and authorize recon overflights"
        ),
    )

    assert [package.mechanical_id for package in result.player_compilation.action_packages] == [
        "cuba_announce_naval_quarantine",
        "cuba_open_kremlin_channel",
        "cuba_recon_overflights",
    ]
    assert {
        package.mechanical_id for package in result.deterministic_result.scheduled_actions
    } == {"cuba_announce_naval_quarantine"}
    assert {
        package.mechanical_id
        for package in result.deterministic_result.accepted_actions
        if package.actor_id == scenario.player_entity_id
    } == {"cuba_open_kremlin_channel", "cuba_recon_overflights"}
    assert "compiled actions: 3" in result.debug_transcript.rendered_text
    assert result.aftermath_report.accepted_actions
    assert result.aftermath_report.scheduled_actions


def test_multi_action_compiler_caps_player_agenda_at_three() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=44)
    orchestrator = TurnOrchestrator(
        action_catalog=scenario.action_catalog,
        capabilities=scenario.capabilities,
        llm_client=ScriptedLLMClient(),
    )

    result = orchestrator.run_turn(
        world,
        player_entity_id=scenario.player_entity_id,
        player_intent=(
            "announce a naval quarantine, keep a backchannel open, authorize recon, "
            "and raise DEFCON readiness"
        ),
    )

    assert len(result.player_compilation.action_packages) == 3
    assert result.player_compilation.unprocessed_intents
    assert any("unprocessed intent" in note for note in result.player_compilation.notes)


def test_multi_action_compiler_hard_rejects_excessive_agendas() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=440)
    orchestrator = TurnOrchestrator(
        action_catalog=scenario.action_catalog,
        capabilities=scenario.capabilities,
        llm_client=ScriptedLLMClient(),
    )

    result = orchestrator.run_turn(
        world,
        player_entity_id=scenario.player_entity_id,
        player_intent=(
            "float a Jupiter trade, offer a non-invasion pledge, prepare an air strike, "
            "raise DEFCON readiness, authorize recon overflights, announce a naval "
            "quarantine, issue a public demand, and keep a backchannel open"
        ),
    )

    assert result.player_compilation.rejected
    assert not result.player_compilation.action_packages
    assert result.player_compilation.unprocessed_intents
    assert any("hard maximum" in error for error in result.player_compilation.errors)


def test_turn_briefing_renders_problems_pressure_agenda_and_action_cards() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=45)

    briefing = build_turn_briefing(
        world,
        player_entity_id=scenario.player_entity_id,
        action_catalog=scenario.action_catalog,
        capabilities=scenario.capabilities,
    )
    rendered = render_turn_briefing(briefing)

    assert briefing.problems
    assert briefing.pressure_indicators
    assert briefing.agenda_budget.max_actions == 3
    assert any(card.capability_id == "cuba_open_kremlin_channel" for card in briefing.action_cards)
    assert "Problems on the table:" in rendered
    assert "Agenda this turn:" in rendered
    assert "Action cards:" in rendered
    assert "truth_metrics" not in rendered
    assert "hidden_clocks" not in rendered


def test_after_action_report_summarizes_player_consequences_before_debug() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=46)
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

    assert rendered.startswith("RESULTS")
    assert "Accepted:" in rendered
    assert "Media desk:" in rendered
    assert "Reconnaissance Confusion" in rendered
    assert "Immediate consequences:" in rendered
    assert "ORCHESTRATED TURN DEBUG" not in rendered
    assert "Council reaction:" in rendered


def test_cuba_scenario_initializes_persistent_advisor_council() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=47)

    council = world.advisor_councils[scenario.player_entity_id]

    assert set(council.advisors) == {
        "state",
        "defense",
        "intelligence",
        "political",
        "legal_un",
    }
    assert council.advisors["state"].trust_channels["backchannel"] > 0.7
    assert council.advisors["defense"].urgency > council.advisors["state"].urgency


def test_dialogue_records_are_saved_in_debug_session() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=42)
    client = ScriptedLLMClient()
    dialogue = DialogueEngineAgent(
        action_catalog=scenario.action_catalog,
        capabilities=scenario.capabilities,
    )
    call_start = len(client.calls)

    response = dialogue.respond_to_player(
        world,
        player_entity_id=scenario.player_entity_id,
        player_message="How do we keep an off-ramp open?",
        llm_client=client,
    )
    recorder = DebugSessionRecorder(
        world_state=world,
        player_entity_id=scenario.player_entity_id,
        output_dir=_test_output_dir("dialogue"),
    )
    recorder.append_dialogue(
        turn=world.turn_number,
        player_message="How do we keep an off-ramp open?",
        response=response,
        llm_calls=client.calls[call_start:],
    )
    loaded = load_debug_session(recorder.save())

    assert loaded.dialogue_records[0].response.suggested_capability_ids
    assert loaded.dialogue_records[0].llm_calls[0].request.label == (
        "dialogue.us_excomm.advisor_response"
    )


def test_tui_formats_live_llm_errors_as_readable_blocks() -> None:
    rendered = _format_runtime_error(
        "Advisor dialogue",
        LlamaCppJSONError(
            "llama.cpp response did not satisfy JSON contract; "
            "task_label=dialogue.us_excomm.advisor_response; "
            "schema=AdvisorCouncilResponse; attempts=2; "
            "diagnostic_artifact=output/diagnostics/ai_invalid_json/example.json"
        ),
    )

    assert rendered.startswith("Advisor dialogue failed.")
    assert "Live LLM error: LlamaCppJSONError" in rendered
    assert "  task_label=dialogue.us_excomm.advisor_response" in rendered
    assert "  schema=AdvisorCouncilResponse" in rendered
    assert "  diagnostic_artifact=output/diagnostics/ai_invalid_json/example.json" in rendered
    assert "Traceback" not in rendered


def _test_output_dir(name: str) -> Path:
    path = Path("output") / "test_debug_sessions" / f"{name}_{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    return path
