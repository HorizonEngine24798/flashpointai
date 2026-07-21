from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from crisis_room.app.debug_sessions import DebugSessionRecorder, load_debug_session
from crisis_room.app.planning import build_player_plan_preview, render_player_plan_preview
from crisis_room.app.turn_orchestrator import TurnOrchestrator
from crisis_room.llm.contracts import FakeLLMClient
from crisis_room.llm.scripted_client import ScriptedLLMClient
from crisis_room.scenario.cuba import build_cuban_missile_crisis_1962_scenario
from crisis_room.state.saves import (
    load_playable_session,
    restore_pending_plan,
    save_playable_session,
)


def test_plan_preview_compiles_actions_and_renders_batch_warnings() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=91)
    client = ScriptedLLMClient()
    orchestrator = TurnOrchestrator(
        action_catalog=scenario.action_catalog,
        capabilities=scenario.capabilities,
        llm_client=client,
    )

    preview = build_player_plan_preview(
        world,
        player_entity_id=scenario.player_entity_id,
        player_intent=(
            "announce a naval quarantine, keep a private Kremlin backchannel open, "
            "and authorize recon overflights"
        ),
        gamemaster=orchestrator.gamemaster,
        action_catalog=scenario.action_catalog,
        capabilities=scenario.capabilities,
        scenario_events=scenario.scenario_events,
    )
    rendered = render_player_plan_preview(
        preview,
        action_catalog=scenario.action_catalog,
        capabilities=scenario.capabilities,
    )

    assert preview.is_committable
    assert [package.mechanical_id for package in preview.compilation.action_packages] == [
        "cuba_announce_naval_quarantine",
        "cuba_open_kremlin_channel",
        "cuba_recon_overflights",
    ]
    assert any(
        warning.code == "public_covert_tension"
        for warning in preview.batch_validation_report.warnings
    )
    assert rendered.startswith("PLAN PREVIEW")
    assert "Compiled actions:" in rendered
    assert "Agenda warnings:" in rendered
    assert "Resource pressure:" in rendered
    assert "Visible flash-event risks:" in rendered
    assert "Known consequences and risks:" in rendered
    assert "Quarantine contact nearing the line" in rendered
    assert "Type COMMIT" in rendered


def test_failed_plan_preview_renders_recovery_hint() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=911)
    client = FakeLLMClient(
        {
            "gamemaster.us_excomm.intent_compilation": {
                "accepted": False,
                "candidates": [],
                "rejected_intents": ["unclear move"],
                "errors": ["no catalog action matched"],
            }
        }
    )
    orchestrator = TurnOrchestrator(
        action_catalog=scenario.action_catalog,
        capabilities=scenario.capabilities,
        llm_client=client,
    )

    preview = build_player_plan_preview(
        world,
        player_entity_id=scenario.player_entity_id,
        player_intent="do something clever",
        gamemaster=orchestrator.gamemaster,
        action_catalog=scenario.action_catalog,
        capabilities=scenario.capabilities,
    )
    rendered = render_player_plan_preview(
        preview,
        action_catalog=scenario.action_catalog,
        capabilities=scenario.capabilities,
    )

    assert not preview.is_committable
    assert "Try next:" in rendered
    assert "Type ACTIONS to inspect legal action names." in rendered
    assert "ACTION open a private Kremlin channel to soviet_presidium" in rendered


def test_committing_precompiled_plan_does_not_recompile_player_intent() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=92)
    client = ScriptedLLMClient()
    orchestrator = TurnOrchestrator(
        action_catalog=scenario.action_catalog,
        capabilities=scenario.capabilities,
        llm_client=client,
    )
    preview = build_player_plan_preview(
        world,
        player_entity_id=scenario.player_entity_id,
        player_intent=(
            "announce a naval quarantine, keep a private Kremlin backchannel open, "
            "and authorize recon overflights"
        ),
        gamemaster=orchestrator.gamemaster,
        action_catalog=scenario.action_catalog,
        capabilities=scenario.capabilities,
    )

    result = orchestrator.run_turn(
        world,
        player_entity_id=scenario.player_entity_id,
        player_intent=preview.player_intent,
        precompiled_player_compilation=preview.compilation,
    )
    labels = [call.request.label for call in result.debug_transcript.llm_calls]

    assert result.player_compilation == preview.compilation
    assert not any(label.startswith("gamemaster.") for label in labels)
    assert {
        package.mechanical_id
        for package in result.deterministic_result.accepted_actions
        if package.actor_id == scenario.player_entity_id
    } == {"cuba_open_kremlin_channel", "cuba_recon_overflights"}
    assert {
        package.mechanical_id for package in result.deterministic_result.scheduled_actions
    } == {"cuba_announce_naval_quarantine"}


def test_plan_previews_are_saved_without_mutating_world_state() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=93)
    client = ScriptedLLMClient()
    orchestrator = TurnOrchestrator(
        action_catalog=scenario.action_catalog,
        capabilities=scenario.capabilities,
        llm_client=client,
    )
    preview = build_player_plan_preview(
        world,
        player_entity_id=scenario.player_entity_id,
        player_intent="open a private Kremlin backchannel for reciprocal restraint",
        gamemaster=orchestrator.gamemaster,
        action_catalog=scenario.action_catalog,
        capabilities=scenario.capabilities,
    )
    rendered = render_player_plan_preview(
        preview,
        action_catalog=scenario.action_catalog,
        capabilities=scenario.capabilities,
    )
    recorder = DebugSessionRecorder(
        world_state=world,
        player_entity_id=scenario.player_entity_id,
        output_dir=_test_output_dir("plan_preview"),
    )

    recorder.append_plan_preview(
        turn=world.turn_number,
        player_intent=preview.player_intent,
        preview=preview,
        rendered_text=rendered,
        llm_calls=client.calls,
    )
    loaded = load_debug_session(recorder.save())

    assert loaded.world_state.turn_number == world.turn_number
    assert loaded.plan_previews[0].preview.player_intent == preview.player_intent
    assert loaded.plan_previews[0].preview.compilation.action_packages[0].mechanical_id == (
        "cuba_open_kremlin_channel"
    )
    assert loaded.plan_previews[0].llm_calls[0].request.label == (
        "gamemaster.us_excomm.intent_compilation"
    )
    assert "PLAN PREVIEW" in loaded.rendered_log[-1]


def test_playable_saves_restore_pending_uncommitted_plan() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=94)
    client = ScriptedLLMClient()
    orchestrator = TurnOrchestrator(
        action_catalog=scenario.action_catalog,
        capabilities=scenario.capabilities,
        llm_client=client,
    )
    preview = build_player_plan_preview(
        world,
        player_entity_id=scenario.player_entity_id,
        player_intent="open a private Kremlin backchannel for reciprocal restraint",
        gamemaster=orchestrator.gamemaster,
        action_catalog=scenario.action_catalog,
        capabilities=scenario.capabilities,
    )

    path = save_playable_session(
        world_state=world,
        player_entity_id=scenario.player_entity_id,
        output_dir=_test_output_dir("playable_save"),
        pending_plan=preview,
    )
    loaded = load_playable_session(path)
    restored = restore_pending_plan(loaded)

    assert loaded.pending_plan is not None
    assert restored is not None
    assert restored.player_intent == preview.player_intent
    assert restored.compilation.action_packages[0].mechanical_id == "cuba_open_kremlin_channel"

    loaded.world_state.turn_number += 1
    assert restore_pending_plan(loaded) is None


def _test_output_dir(name: str) -> Path:
    path = Path("output") / "test_debug_sessions" / f"{name}_{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    return path
