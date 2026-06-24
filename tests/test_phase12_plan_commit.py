from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from crisis_room.app.debug_sessions import DebugSessionRecorder, load_debug_session
from crisis_room.app.planning import build_player_plan_preview, render_player_plan_preview
from crisis_room.app.turn_orchestrator import TurnOrchestrator
from crisis_room.llm.scripted_client import ScriptedLLMClient
from crisis_room.scenario.schema import build_cuban_missile_crisis_1962_scenario


def test_plan_preview_compiles_actions_and_renders_batch_warnings() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=91)
    client = ScriptedLLMClient()
    orchestrator = TurnOrchestrator(
        action_catalog=scenario.action_catalog,
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
    )
    rendered = render_player_plan_preview(
        preview,
        action_catalog=scenario.action_catalog,
    )

    assert preview.is_committable
    assert [package.action_id for package in preview.compilation.action_packages] == [
        "announce_quarantine",
        "private_kremlin_backchannel",
        "authorize_recon_overflights",
    ]
    assert any(
        warning.code == "public_covert_tension"
        for warning in preview.batch_validation_report.warnings
    )
    assert rendered.startswith("PLAN PREVIEW")
    assert "Compiled actions:" in rendered
    assert "Agenda warnings:" in rendered
    assert "Type COMMIT" in rendered


def test_committing_precompiled_plan_does_not_recompile_player_intent() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=92)
    client = ScriptedLLMClient()
    orchestrator = TurnOrchestrator(
        action_catalog=scenario.action_catalog,
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
        package.action_id
        for package in result.deterministic_result.accepted_actions
        if package.actor_id == scenario.player_entity_id
    } == {"private_kremlin_backchannel", "authorize_recon_overflights"}
    assert {
        package.action_id for package in result.deterministic_result.scheduled_actions
    } == {"announce_quarantine"}


def test_plan_previews_are_saved_without_mutating_world_state() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=93)
    client = ScriptedLLMClient()
    orchestrator = TurnOrchestrator(
        action_catalog=scenario.action_catalog,
        llm_client=client,
    )
    preview = build_player_plan_preview(
        world,
        player_entity_id=scenario.player_entity_id,
        player_intent="open a private Kremlin backchannel for reciprocal restraint",
        gamemaster=orchestrator.gamemaster,
        action_catalog=scenario.action_catalog,
    )
    rendered = render_player_plan_preview(
        preview,
        action_catalog=scenario.action_catalog,
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
    assert loaded.plan_previews[0].preview.compilation.action_packages[0].action_id == (
        "private_kremlin_backchannel"
    )
    assert loaded.plan_previews[0].llm_calls[0].request.label == (
        "gamemaster.us_excomm.intent_compilation"
    )
    assert "PLAN PREVIEW" in loaded.rendered_log[-1]


def _test_output_dir(name: str) -> Path:
    path = Path("output") / "test_debug_sessions" / f"{name}_{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    return path
