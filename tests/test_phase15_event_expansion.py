from __future__ import annotations

import pytest

from crisis_room.engine.actions import ActionPackage
from crisis_room.engine.adjudication import DeterministicEngineV2, DeterministicTurnResult
from crisis_room.llm.task_contracts import EventCandidate
from crisis_room.scenario.event_choices import (
    build_event_choice_action,
    update_event_choices_from_actions,
)
from crisis_room.scenario.events import (
    ScenarioEventSettings,
    resolve_scenario_events,
)
from crisis_room.scenario.cuba import build_cuban_missile_crisis_1962_scenario
from crisis_room.state.events import ScenarioEventChoiceStatus
from crisis_room.state.signals import SignalChannel


def test_multiple_authored_events_can_fire_when_density_policy_allows() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=151)
    world.hidden_clocks["command_and_control_risk"] = 0.36
    world.truth_metrics["escalation_pressure"] = 0.7
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
                submitted_turn=world.turn_number,
            ),
            ActionPackage(
                actor_id=scenario.player_entity_id,
                action_id="reconnaissance",
                capability_id="cuba_recon_overflights",
                target_ids=["cuba"],
                channel=SignalChannel.INTEL,
                intent_summary="Authorize reconnaissance overflights.",
                submitted_turn=world.turn_number,
            ),
        ],
    )

    resolution = resolve_scenario_events(
        deterministic_result.world_state,
        scenario.scenario_events,
        deterministic_result=deterministic_result,
        player_entity_id=scenario.player_entity_id,
        event_settings=scenario.event_settings,
    )

    assert [record.event_id for record in resolution.fired_events] == [
        "quarantine_contact_warning",
        "recon_air_defense_scare",
    ]
    assert len(resolution.world_state.event_history) == 2


def test_llm_event_candidate_requires_deterministic_approval_and_clamps_effects() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=152)
    settings = ScenarioEventSettings(
        base_max_events_per_turn=1,
        allow_llm_event_candidates=True,
        llm_candidate_min_plausibility=0.6,
        llm_candidate_min_escalation_pressure=0.5,
        llm_candidate_effect_clamp=0.03,
    )
    approved = EventCandidate.model_validate(
        {
            "candidate_id": "press_confusion",
            "kind": "chaos",
            "title": "Press Confusion",
            "summary": "Conflicting public reports force the room to react.",
            "plausibility": 0.8,
            "escalation_pressure": 0.7,
            "target_entity_ids": ["us_excomm"],
            "suggested_signals": [
                {
                    "target_entity_ids": ["us_excomm"],
                    "channel": "media",
                    "payload_type": "media_report",
                    "content": "Conflicting public reports circulate around Cuba.",
                    "visibility": "public",
                }
            ],
            "deterministic_effect_hints": {"public_alarm": 0.5},
        }
    )

    resolution = resolve_scenario_events(
        world,
        [],
        player_entity_id=scenario.player_entity_id,
        event_settings=settings,
        event_candidate=approved,
    )

    assert [record.event_id for record in resolution.fired_events] == [
        "llm_candidate_press_confusion"
    ]
    assert resolution.world_state.public_metrics["public_alarm"] == pytest.approx(
        world.public_metrics["public_alarm"] + 0.03
    )
    assert resolution.emitted_signals

    rejected = approved.model_copy(update={"candidate_id": "bad", "plausibility": 0.2})
    rejected_resolution = resolve_scenario_events(
        world,
        [],
        player_entity_id=scenario.player_entity_id,
        event_settings=settings,
        event_candidate=rejected,
    )

    assert rejected_resolution.fired_events == []
    assert rejected_resolution.emitted_signals == []
    assert any("plausibility below threshold" in item for item in rejected_resolution.trace)


def test_event_choice_persists_and_resolves_through_capability_action() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=153)
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
                submitted_turn=world.turn_number,
            )
        ],
    )
    resolution = resolve_scenario_events(
        deterministic_result.world_state,
        scenario.scenario_events,
        deterministic_result=deterministic_result,
        player_entity_id=scenario.player_entity_id,
        event_settings=scenario.event_settings,
    )
    choice = resolution.world_state.pending_event_choices[0]

    assert choice.active_for(resolution.world_state.turn_number, scenario.player_entity_id)
    assert choice.options[0].consumes_normal_action_budget is True

    package, errors = build_event_choice_action(
        resolution.world_state,
        player_entity_id=scenario.player_entity_id,
        choice_query="latest",
        option_query="private_probe",
    )
    assert errors == []
    assert package is not None
    assert package.action_id == "private_diplomacy"
    assert package.capability_id == "cuba_open_kremlin_channel"
    assert package.metadata["event_choice_id"] == choice.choice_id

    scheduled_world = resolution.world_state.model_copy(deep=True)
    update_event_choices_from_actions(
        scheduled_world,
        DeterministicTurnResult(
            world_state=scheduled_world,
            scheduled_actions=[package],
        ),
    )
    assert (
        scheduled_world.pending_event_choices[0].status
        == ScenarioEventChoiceStatus.PENDING
    )

    choice_result = engine.resolve_actions(resolution.world_state, [package])
    update_event_choices_from_actions(choice_result.world_state, choice_result)

    resolved_choice = choice_result.world_state.pending_event_choices[0]
    assert resolved_choice.status == ScenarioEventChoiceStatus.RESOLVED
    assert resolved_choice.selected_option_id == "private_probe"
