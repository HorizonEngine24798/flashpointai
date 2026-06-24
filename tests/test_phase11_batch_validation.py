from __future__ import annotations

from crisis_room.app.presentation import render_aftermath_report
from crisis_room.app.turn_orchestrator import TurnOrchestrator
from crisis_room.engine.actions import ActionPackage
from crisis_room.engine.batch_validation import build_batch_validation_report
from crisis_room.llm.scripted_client import ScriptedLLMClient
from crisis_room.scenario.schema import build_cuban_missile_crisis_1962_scenario
from crisis_room.state.signals import SignalChannel


def test_batch_validation_reports_common_multi_action_conflicts() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=81)
    world.actors["us_excomm"].resources["political_capital"] = 2

    report = build_batch_validation_report(
        world,
        [
            ActionPackage(
                package_id="pkg_quarantine_a",
                actor_id="us_excomm",
                action_id="announce_quarantine",
                target_ids=["soviet_presidium"],
                channel=SignalChannel.PUBLIC,
                intent_summary="Prepare public naval pressure.",
            ),
            ActionPackage(
                package_id="pkg_quarantine_b",
                actor_id="us_excomm",
                action_id="announce_quarantine",
                target_ids=["soviet_presidium"],
                channel=SignalChannel.PUBLIC,
                intent_summary="Duplicate the same prepared pressure.",
            ),
            ActionPackage(
                package_id="pkg_jupiter",
                actor_id="us_excomm",
                action_id="secret_jupiter_trade",
                target_ids=["soviet_presidium"],
                channel=SignalChannel.BACKCHANNEL,
                intent_summary="Float a private Jupiter trade.",
            ),
            ActionPackage(
                package_id="pkg_fallback",
                actor_id="us_excomm",
                action_id="offer_non_invasion_pledge",
                target_ids=["soviet_presidium"],
                channel=SignalChannel.PRIVATE_DIPLOMATIC,
                intent_summary="Offer a pledge only if pressure fails.",
                fallback_condition="if the quarantine does not move Moscow",
            ),
            ActionPackage(
                package_id="pkg_soviet_quarantine_a",
                actor_id="soviet_presidium",
                action_id="announce_quarantine",
                target_ids=["us_excomm"],
                channel=SignalChannel.PUBLIC,
                intent_summary="Non-player duplicate setup.",
            ),
            ActionPackage(
                package_id="pkg_soviet_quarantine_b",
                actor_id="soviet_presidium",
                action_id="announce_quarantine",
                target_ids=["us_excomm"],
                channel=SignalChannel.PUBLIC,
                intent_summary="Non-player duplicate setup again.",
            ),
        ],
        scenario.action_catalog,
        player_entity_id=scenario.player_entity_id,
    )

    player_warnings = [
        warning for warning in report.warnings if warning.actor_id == scenario.player_entity_id
    ]
    player_codes = {warning.code for warning in player_warnings}

    assert {
        "duplicate_cooldown_action",
        "fallback_submitted_now",
        "missing_backchannel_thread",
        "public_covert_tension",
        "resource_contention",
    }.issubset(player_codes)
    assert all(warning.player_visible for warning in player_warnings)
    assert any(
        warning.actor_id == "soviet_presidium" and not warning.player_visible
        for warning in report.warnings
    )


def test_turn_orchestrator_surfaces_player_batch_warnings() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=82)
    orchestrator = TurnOrchestrator(
        action_catalog=scenario.action_catalog,
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
    rendered = render_aftermath_report(result.aftermath_report)

    assert result.batch_validation_report is not None
    assert result.debug_transcript.batch_validation_report == result.batch_validation_report
    assert any(
        warning.code == "public_covert_tension"
        for warning in result.batch_validation_report.warnings
    )
    assert result.aftermath_report.batch_warnings
    assert "Agenda warnings:" in rendered
    assert "[batch_validation]" in result.debug_transcript.rendered_text
