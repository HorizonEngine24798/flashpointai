from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from crisis_room.agents.base import AgentOutput
from crisis_room.agents.dialogue_engine import DialogueEngineAgent
from crisis_room.app.debug_sessions import DebugSessionRecorder, load_debug_session
from crisis_room.app.presentation import (
    TurnAftermathReport,
    build_turn_aftermath_report,
    build_turn_briefing,
    render_action_cards,
    render_aftermath_report,
    render_public_timeline,
    render_turn_briefing,
)
from crisis_room.app.runtime_helpers import format_runtime_error
from crisis_room.app.runtime_helpers import ADVISOR_RETRY_TEXT
from crisis_room.app.session import GameSession
from crisis_room.app.turn_orchestrator import (
    RECOVERABLE_PLAYER_ACTION_TEXT,
    RecoverablePlayerActionError,
    TurnOrchestrator,
)
from crisis_room.app.tui import _print_debug_dump, _print_last_turn
from crisis_room.engine.adjudication import DeterministicTurnResult
from crisis_room.llm.diagnostics import LlamaCppJSONError
from crisis_room.llm.contracts import FakeLLMClient, LLMCallRecord
from crisis_room.llm.scripted_client import ScriptedLLMClient
from crisis_room.scenario.cuba import build_cuban_missile_crisis_1962_scenario
from crisis_room.web.api import create_app

EXPECTED_TURN_GAMEPLAY_LABELS = [
    "gamemaster.us_excomm.intent_compilation",
    "faction.soviet_presidium.turn",
    "faction.cuba.turn",
    "faction.nato_allies.turn",
    "international.international.pressure",
    "event_creator.event_creator.media_event_turn",
]


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
    assert _gameplay_call_labels(first.debug_transcript.llm_calls) == (
        EXPECTED_TURN_GAMEPLAY_LABELS
    )
    assert _gameplay_call_labels(second.debug_transcript.llm_calls) == (
        EXPECTED_TURN_GAMEPLAY_LABELS
    )
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
    assert "resolves on turn 2" in render_aftermath_report(result.aftermath_report)


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


def test_multi_action_compiler_keeps_legal_prefix_of_excessive_agendas() -> None:
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

    assert len(result.player_compilation.action_packages) == 3
    assert not result.player_compilation.rejected
    assert result.player_compilation.unprocessed_intents
    assert any(
        "above the hard maximum" in intent
        for intent in result.player_compilation.unprocessed_intents
    )
    assert result.world_state.turn_number == 2


def test_failed_player_action_does_not_advance_turn() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=441)
    client = FakeLLMClient(_invalid_direct_message_responses())
    orchestrator = TurnOrchestrator(
        action_catalog=scenario.action_catalog,
        capabilities=scenario.capabilities,
        llm_client=client,
    )

    with pytest.raises(RecoverablePlayerActionError) as exc_info:
        orchestrator.run_turn(
            world,
            player_entity_id=scenario.player_entity_id,
            player_intent="ACTION send a direct Kremlin backchannel message",
        )

    message = str(exc_info.value)
    assert RECOVERABLE_PLAYER_ACTION_TEXT in message
    assert "This action needs a message." in message
    assert world.turn_number == 1
    assert [call.request.label for call in client.calls] == [
        "gamemaster.us_excomm.intent_compilation"
    ]


def test_gui_freeform_action_gets_retry_text_without_advancing() -> None:
    session = GameSession(
        llm_client=FakeLLMClient(_invalid_direct_message_responses()),
        output_dir=_test_output_dir("recoverable_gui") / "debug",
        save_dir=_test_output_dir("recoverable_gui") / "saves",
    )

    with pytest.raises(RecoverablePlayerActionError) as exc_info:
        session.submit_freeform_action("send a direct Kremlin backchannel message")

    assert RECOVERABLE_PLAYER_ACTION_TEXT in str(exc_info.value)
    assert session.world.turn_number == 1


def test_gui_api_gets_retry_text_without_advancing() -> None:
    def session_factory(**kwargs) -> GameSession:
        return GameSession(
            llm_client=FakeLLMClient(_invalid_direct_message_responses()),
            **kwargs,
        )

    app = create_app(
        session_factory=session_factory,
        output_dir=_test_output_dir("recoverable_api") / "debug",
        save_dir=_test_output_dir("recoverable_api") / "saves",
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/action/freeform",
            json={"text": "send a direct Kremlin backchannel message"},
        )
        state = client.get("/api/state")

    assert response.status_code == 400
    assert RECOVERABLE_PLAYER_ACTION_TEXT in response.json()["detail"]
    assert state.json()["turn"]["turn_number"] == 1


def test_gui_advisor_json_failure_gets_retry_text_without_advancing() -> None:
    llm = _BrokenAdvisorLLM()
    session = GameSession(
        llm_client=llm,
        output_dir=_test_output_dir("advisor_retry") / "debug",
        save_dir=_test_output_dir("advisor_retry") / "saves",
    )

    with pytest.raises(ValueError) as exc_info:
        session.ask_advisors("How do we keep an off-ramp open?")

    assert str(exc_info.value) == ADVISOR_RETRY_TEXT
    dialogue_calls = [call for call in llm.calls if call.label.startswith("dialogue.")]
    assert len(dialogue_calls) == 2
    assert "Retry instruction" in dialogue_calls[1].messages[-1].content
    assert session.world.turn_number == 1


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


def test_turn_briefing_can_hide_repeated_action_cards() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=451)
    briefing = build_turn_briefing(
        world,
        player_entity_id=scenario.player_entity_id,
        action_catalog=scenario.action_catalog,
        capabilities=scenario.capabilities,
    )

    compact = render_turn_briefing(briefing, include_action_cards=False)
    cards = render_action_cards(briefing)
    first_card = briefing.action_cards[0]

    assert "Action cards hidden. Type ACTIONS" in compact
    assert f"[{first_card.category}] {first_card.title}" not in compact
    assert f"[{first_card.category}] {first_card.title}" in cards


def test_turn_briefing_surfaces_critical_risk_warning() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=453)
    world.hidden_clocks["nuclear_escalation"] = 0.82

    briefing = build_turn_briefing(
        world,
        player_entity_id=scenario.player_entity_id,
        action_catalog=scenario.action_catalog,
        capabilities=scenario.capabilities,
    )

    rendered = render_turn_briefing(briefing)
    assert briefing.critical_warnings
    assert "Nuclear Exchange threshold is near" in rendered


def test_media_rendering_keeps_results_scannable_and_media_expanded() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=452)
    report = TurnAftermathReport(
        turn_number=1,
        media_headlines=[
            "Markets Slide: A long generated summary crowds the turn.",
            "UN Corridor: Another generated summary repeats the pressure.",
        ],
    )

    aftermath = render_aftermath_report(report)
    media = render_public_timeline(world, limit=1)

    assert "Markets Slide" in aftermath
    assert "long generated summary" not in aftermath
    assert "1 more media update. Type MEDIA" in aftermath
    assert media.startswith("MEDIA")
    assert world.public_timeline.entries[-1].title in media
    assert world.public_timeline.entries[-1].summary in media


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
    assert "Observed shifts this turn:" in rendered
    assert "Decision impact:" in rendered
    assert "Backchannel viability" in rendered
    assert "Immediate consequences:" not in rendered
    assert "ORCHESTRATED TURN DEBUG" not in rendered
    assert "Council reaction:" in rendered


def test_full_scripted_turn_replays_from_same_campaign_seed() -> None:
    def play_once():
        scenario = build_cuban_missile_crisis_1962_scenario()
        result = TurnOrchestrator(
            action_catalog=scenario.action_catalog,
            capabilities=scenario.capabilities,
            scenario_events=scenario.scenario_events,
            scenario_endings=scenario.scenario_endings,
            pressure_rules=scenario.pressure_rules,
            hidden_obligations=scenario.hidden_obligations,
            event_settings=scenario.event_settings,
            llm_client=ScriptedLLMClient(),
        ).run_turn(
            scenario.create_initial_world(rng_seed=73),
            player_entity_id=scenario.player_entity_id,
            player_intent="open a private Kremlin backchannel for reciprocal restraint",
        )
        return result.world_state.model_dump(mode="json")

    assert play_once() == play_once()


def test_after_action_report_summarizes_invalid_npc_actions_without_debug_noise() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=461)
    report = build_turn_aftermath_report(
        before_world_state=world,
        after_world_state=world,
        player_entity_id=scenario.player_entity_id,
        action_catalog=scenario.action_catalog,
        capabilities=scenario.capabilities,
        deterministic_result=DeterministicTurnResult(world_state=world),
        agent_outputs={
            "soviet_presidium": AgentOutput(
                entity_id="soviet_presidium",
                perception_summary="The faction hesitated.",
                debug_notes=[
                    "decision failed deterministic validation: actor type opposing_faction cannot perform cuba_secret_jupiter_trade"
                ],
            )
        },
    )

    rendered = render_aftermath_report(report)

    assert "soviet_presidium: no effective move" in rendered
    assert "attempted no valid action" not in rendered
    assert "actor type opposing_faction" not in rendered


def test_tui_last_turn_prefers_player_visible_result(capsys) -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=453)
    recorder = DebugSessionRecorder(
        world_state=world,
        player_entity_id=scenario.player_entity_id,
    )
    recorder.record.rendered_log.extend(
        [
            "ORCHESTRATED TURN DEBUG\nraw internals",
            "RESULTS\nAccepted:\n- Public line",
        ]
    )

    _print_last_turn(recorder)

    rendered = capsys.readouterr().out
    assert rendered.startswith("RESULTS")
    assert "ORCHESTRATED TURN DEBUG" not in rendered


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
        "personal",
    }
    assert council.advisors["state"].trust_channels["backchannel"] > 0.7
    assert council.advisors["defense"].urgency > council.advisors["state"].urgency
    assert council.advisors["personal"].hidden_metric_access
    assert council.advisors["personal"].loyal_to_player


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
    rendered = format_runtime_error(
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


def test_advisor_retry_text_hides_diagnostics_until_debug() -> None:
    from crisis_room.app.runtime_helpers import format_advisor_retry_error

    exc = LlamaCppJSONError(
        "task_label=dialogue.us_excomm.advisor_response; "
        "diagnostic_artifact=output/diagnostics/example.json"
    )

    assert format_advisor_retry_error(exc) == ADVISOR_RETRY_TEXT
    debug = format_advisor_retry_error(exc, debug_mode=True)
    assert ADVISOR_RETRY_TEXT in debug
    assert "diagnostic_artifact=output/diagnostics/example.json" in debug


def test_tui_dump_mode_prints_full_debug_state(capsys) -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=48)
    orchestrator = TurnOrchestrator(
        action_catalog=scenario.action_catalog,
        capabilities=scenario.capabilities,
        scenario_events=scenario.scenario_events,
        scenario_endings=scenario.scenario_endings,
        pressure_rules=scenario.pressure_rules,
        hidden_obligations=scenario.hidden_obligations,
        event_settings=scenario.event_settings,
        llm_client=ScriptedLLMClient(),
    )
    recorder = DebugSessionRecorder(
        world_state=world,
        player_entity_id=scenario.player_entity_id,
    )

    _print_debug_dump(
        scenario=scenario,
        world=world,
        player_id=scenario.player_entity_id,
        orchestrator=orchestrator,
        recorder=recorder,
        pending_plan=None,
    )

    rendered = capsys.readouterr().out

    assert "DEBUG DUMP" in rendered
    assert '"visibility": "dump"' in rendered
    assert '"hidden_obligations"' in rendered
    assert '"llm_calls": []' in rendered
    assert '"private_goals"' in rendered
    assert '"truth_metrics"' in rendered
    assert '"debug_session"' in rendered


def _test_output_dir(name: str) -> Path:
    path = Path("output") / "test_debug_sessions" / f"{name}_{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _gameplay_call_labels(calls: list[LLMCallRecord]) -> list[str]:
    return [
        call.request.label
        for call in calls
        if not call.request.label.startswith("info_channel.")
    ]


def _invalid_direct_message_responses() -> dict[str, object]:
    return {
        "gamemaster.us_excomm.intent_compilation": {
            "accepted": True,
            "candidates": [
                {
                    "accepted": True,
                    "action_id": "backchannel_message",
                    "capability_id": "cuba_direct_kremlin_message",
                    "target_ids": ["soviet_presidium"],
                    "channel": "backchannel",
                    "intent_summary": "Send a direct Kremlin message.",
                    "parameters": {},
                }
            ],
        }
    }


class _BrokenAdvisorLLM:
    def __init__(self) -> None:
        self.calls: list[object] = []

    def complete_json(self, request, response_model):
        self.calls.append(request)
        raise LlamaCppJSONError(
            "task_label=dialogue.us_excomm.advisor_response; "
            "diagnostic_artifact=output/diagnostics/example.json"
        )
