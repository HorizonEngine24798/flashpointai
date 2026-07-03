from __future__ import annotations

import os
from pathlib import Path

import pytest

from crisis_room.app.turn_orchestrator import TurnOrchestrator
from crisis_room.config.settings import LlamaCppSettings, load_settings
from crisis_room.llm.llama_cpp_client import LlamaCppServerClient
from crisis_room.llm.preflight import build_preflight_report, start_preflight_server
from crisis_room.llm.smoke import run_smoke
from crisis_room.scenario.schema import build_cuban_missile_crisis_1962_scenario


pytestmark = [
    pytest.mark.live_llm,
    pytest.mark.slow,
    pytest.mark.skipif(
        os.getenv("CRISIS_ROOM_RUN_LIVE_LLM_TESTS") != "1",
        reason="set CRISIS_ROOM_RUN_LIVE_LLM_TESTS=1 to run live llama.cpp tests",
    ),
]

EXPECTED_ONE_TURN_LABELS = [
    "dialogue.us_excomm.advisor_response",
    "gamemaster.us_excomm.intent_compilation",
    "faction.soviet_presidium.turn",
    "faction.cuba.turn",
    "faction.nato_allies.turn",
    "international.international.pressure",
    "event_creator.event_creator.media_event_turn",
]


def test_live_llm_config_preflight() -> None:
    settings = _live_settings()

    report = build_preflight_report(settings, config_source=_live_config_source())

    assert report.ok, report.errors
    assert report.normalized_base_url == settings.base_url
    if settings.manage_server:
        assert report.executable.exists
        assert report.model.exists
        assert report.command


def test_live_llm_managed_startup_readiness() -> None:
    settings = _live_settings()
    report = build_preflight_report(settings, config_source=_live_config_source())
    assert report.ok, report.errors

    start_report = start_preflight_server(settings)

    assert start_report.ok, start_report.error
    assert start_report.status in {"ready", "not-started"}


def test_live_llm_smoke_json_contract() -> None:
    settings = _live_settings()
    report = build_preflight_report(settings, config_source=_live_config_source())
    assert report.ok, report.errors

    response = run_smoke(settings)

    assert response.ok
    assert response.answer == "hello"


def test_live_llm_one_turn_orchestrator_records_all_contracts() -> None:
    settings = _live_settings()
    report = build_preflight_report(settings, config_source=_live_config_source())
    assert report.ok, report.errors

    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=61)
    client = LlamaCppServerClient(settings)
    try:
        orchestrator = TurnOrchestrator(
            action_catalog=scenario.action_catalog,
            capabilities=scenario.capabilities,
            llm_client=client,
        )

        result = orchestrator.run_turn(
            world,
            player_entity_id=scenario.player_entity_id,
            player_message="How do we keep an off-ramp open?",
            player_intent="open a private Kremlin backchannel for reciprocal restraint",
            scenario_notes=["Live Cuba regression should remain plausible and compact."],
        )
    finally:
        client.close()

    calls = result.debug_transcript.llm_calls
    gameplay_calls = [
        call for call in calls if not call.request.label.startswith("info_channel.")
    ]
    assert result.world_state.turn_number == 2
    assert [call.request.label for call in gameplay_calls] == EXPECTED_ONE_TURN_LABELS
    assert all(call.raw_response is not None for call in calls)
    assert all(call.parsed_response is not None for call in calls)
    assert not result.player_compilation.rejected
    assert result.player_compilation.action_package is not None
    assert result.deterministic_result.accepted_actions
    assert result.final_routing_result.deliveries


def _live_settings() -> LlamaCppSettings:
    config_path = _live_config_path()
    if not config_path.exists():
        pytest.fail(
            "live llama.cpp config file is required when "
            "CRISIS_ROOM_RUN_LIVE_LLM_TESTS=1; set CRISIS_ROOM_CONFIG_PATH or create "
            f"{config_path}"
        )
    return load_settings(config_path).llama_cpp


def _live_config_source() -> str:
    return f"live test config: {_live_config_path()}"


def _live_config_path() -> Path:
    return Path(os.getenv("CRISIS_ROOM_CONFIG_PATH", "config/llama_cpp.local.json"))
