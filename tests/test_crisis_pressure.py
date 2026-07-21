from __future__ import annotations

from crisis_room.agents.context import build_visible_context
from crisis_room.agents.gamemaster import GamemasterCompilation
from crisis_room.app.presentation import build_turn_briefing, render_aftermath_report
from crisis_room.app.turn_orchestrator import TurnOrchestrator
from crisis_room.engine.actions import ActionCategory, ActionDefinition, ActionPackage
from crisis_room.engine.adjudication import DeterministicTurnResult
from crisis_room.llm.contracts import FakeLLMClient
from crisis_room.llm.scripted_client import ScriptedLLMClient
from crisis_room.scenario.endings import evaluate_ending_events
from crisis_room.scenario.events import (
    ScenarioEventDefinition,
    ScenarioEventEffect,
    ScenarioEventTrigger,
    resolve_scenario_events,
)
from crisis_room.scenario.pressure import (
    HiddenObligation,
    PressureRule,
    apply_scenario_pressure,
)
from crisis_room.scenario.cuba import build_cuban_missile_crisis_1962_scenario
from crisis_room.state.signals import SignalChannel
from crisis_room.state.world import EntityState, EntityType, WorldStateV2


def test_pressure_rules_apply_to_accepted_actions() -> None:
    world = _world({"foo": 0.0})
    action = _action("diplomatic_move", category="diplomatic")
    result = DeterministicTurnResult(world_state=world, accepted_actions=[action])

    pressure = apply_scenario_pressure(
        world,
        pressure_rules=[
            PressureRule(
                rule_id="foo_tax",
                applies_to_categories=["diplomatic"],
                effects=ScenarioEventEffect(truth_metric_effects={"foo": 0.2}),
            )
        ],
        hidden_obligations=[],
        deterministic_result=result,
    )

    assert pressure.world_state.truth_metrics["foo"] == 0.2
    assert pressure.applications[0].rule_id == "foo_tax"


def test_hidden_obligations_miss_unless_covered() -> None:
    obligation = HiddenObligation(
        obligation_id="keep_watch",
        title="Keep Watch",
        covered_by_capability_ids=["watch"],
        missed_effects=ScenarioEventEffect(clock_effects={"danger": 0.3}),
    )
    world = _world(hidden_clocks={"danger": 0.0})

    missed = apply_scenario_pressure(
        world,
        pressure_rules=[],
        hidden_obligations=[obligation],
        deterministic_result=DeterministicTurnResult(
            world_state=world,
            accepted_actions=[_action("talk", capability_id="talk")],
        ),
    )
    covered = apply_scenario_pressure(
        world,
        pressure_rules=[],
        hidden_obligations=[obligation],
        deterministic_result=DeterministicTurnResult(
            world_state=world,
            accepted_actions=[_action("talk", capability_id="watch")],
        ),
    )

    assert missed.world_state.hidden_clocks["danger"] == 0.3
    assert covered.world_state.hidden_clocks["danger"] == 0.0


def test_concrete_diplomatic_offer_creates_settlement_framework() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=200)
    action = ActionPackage(
        actor_id=scenario.player_entity_id,
        action_id="private_diplomacy",
        capability_id="cuba_offer_non_invasion_pledge",
        target_ids=["soviet_presidium"],
        channel=SignalChannel.PRIVATE_DIPLOMATIC,
        intent_summary="Offer a reciprocal non-invasion settlement term.",
    )

    pressure = apply_scenario_pressure(
        world,
        pressure_rules=scenario.pressure_rules,
        hidden_obligations=[],
        deterministic_result=DeterministicTurnResult(
            world_state=world,
            accepted_actions=[action],
        ),
    )

    assert "settlement_framework_offered" in pressure.world_state.active_commitments


def test_orchestrator_applies_pressure_before_scenario_events() -> None:
    action = ActionDefinition(
        action_id="diplomatic_move",
        title="Diplomatic Move",
        category=ActionCategory.DIPLOMATIC,
        actor_ids_allowed=["player"],
        channels_allowed=[SignalChannel.PRIVATE_DIPLOMATIC],
    )
    event = ScenarioEventDefinition(
        event_id="foo_threshold",
        title="Foo Threshold",
        summary="Pressure crossed the threshold.",
        trigger=ScenarioEventTrigger(truth_metric_minimums={"foo": 0.2}),
    )
    llm = FakeLLMClient(
        {
            "gamemaster.player.intent_compilation": {
                "accepted": True,
                "candidates": [
                    {
                        "accepted": True,
                        "action_id": "diplomatic_move",
                        "target_ids": [],
                        "channel": "private_diplomatic",
                        "intent_summary": "Make the diplomatic move.",
                    }
                ],
            },
            "event_creator.event_creator.media_event_turn": {
                "public_brief": {
                    "headline": "Quiet Turn",
                    "summary": "No public bulletin yet.",
                },
                "event_candidate": None,
            },
        }
    )
    orchestrator = TurnOrchestrator(
        action_catalog=[action],
        llm_client=llm,
        scenario_events=[event],
        pressure_rules=[
            PressureRule(
                rule_id="foo_tax",
                applies_to_action_ids=["diplomatic_move"],
                effects=ScenarioEventEffect(truth_metric_effects={"foo": 0.2}),
            )
        ],
    )

    result = orchestrator.run_turn(
        _world({"foo": 0.0}),
        player_entity_id="player",
        player_intent="move",
    )

    assert result.scenario_event_result is not None
    assert [record.event_id for record in result.scenario_event_result.fired_events] == [
        "foo_threshold"
    ]
    assert "[scenario_pressure]" in result.debug_transcript.rendered_text


def test_cuba_domestic_combo_event_requires_all_thresholds() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=201)
    world.truth_metrics["hawk_pressure"] = 0.76
    world.truth_metrics["perceived_weakness"] = 0.64
    world.public_metrics["public_confidence"] = 0.55

    not_yet = resolve_scenario_events(world, scenario.scenario_events, max_events=3)
    ready_world = world.model_copy(deep=True)
    ready_world.truth_metrics["perceived_weakness"] = 0.66
    ready = resolve_scenario_events(ready_world, scenario.scenario_events, max_events=3)

    assert "security_chiefs_demand_hard_line" not in [
        record.event_id for record in not_yet.fired_events
    ]
    assert "security_chiefs_demand_hard_line" in [
        record.event_id for record in ready.fired_events
    ]


def test_cuba_domestic_failure_ending_is_offered() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=202)
    world.truth_metrics["domestic_trust"] = 0.14
    world.truth_metrics["institutional_loyalty"] = 0.24

    ending = evaluate_ending_events(
        world,
        scenario.scenario_endings,
        player_entity_id=scenario.player_entity_id,
    )

    assert ending.offer_record is not None
    assert ending.offer_record.ending_id == "ousted"


def test_hidden_pressure_is_banded_for_hidden_access_advisor() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=203)
    context = build_visible_context(
        world.actors[scenario.player_entity_id],
        world,
        action_catalog=scenario.action_catalog,
        capabilities=scenario.capabilities,
    )

    bands = context["advisor_council"]["hidden_pressure_bands"]
    assert context["advisor_council"]["advisors"][-1]["advisor_id"] == "personal"
    assert context["advisor_council"]["advisors"][-1]["hidden_metric_access"] is True
    assert bands["domestic_trust"] == "rising"
    assert all(isinstance(value, str) for value in bands.values())
    assert "truth_metrics" not in context
    assert "hidden_clocks" not in context


def test_pressure_briefing_rollups_include_related_crisis_state() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=204)
    world.truth_metrics["escalation_pressure"] = 0.0
    world.hidden_clocks["nuclear_escalation"] = 0.0
    world.hidden_clocks["command_and_control_risk"] = 0.8
    world.public_metrics["public_alarm"] = 0.9
    world.truth_metrics["missile_operational_progress"] = 0.8
    world.truth_metrics["hawk_pressure"] = 0.8

    briefing = build_turn_briefing(
        world,
        player_entity_id=scenario.player_entity_id,
        action_catalog=scenario.action_catalog,
        capabilities=scenario.capabilities,
    )

    indicators = {indicator.key: indicator for indicator in briefing.pressure_indicators}
    assert indicators["escalation"].band != "low"
    assert indicators["backchannel_viability"].label == "Backchannel fragility"
    assert indicators["alliance_cohesion"].label == "Alliance strain"


def test_passive_cuba_turn_surfaces_internal_pressure() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=204)
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

    result = orchestrator.run_turn(
        world,
        player_entity_id=scenario.player_entity_id,
        player_intent="hold no action this turn",
        precompiled_player_compilation=GamemasterCompilation(action_packages=[]),
        allow_empty_player_action=True,
    )
    rendered = render_aftermath_report(result.aftermath_report)

    assert result.aftermath_report.pressure_updates
    assert "Internal pressure:" in rendered
    assert "Missile readiness gains time" in rendered
    for entity_id in ["soviet_presidium", "cuba", "nato_allies"]:
        assert any(
            entry.title == "No Visible Player Move"
            for entry in result.world_state.entity_timelines[entity_id].entries
        )


def test_pressure_runtime_accepts_non_cuba_metric_names() -> None:
    world = _world({"ring_temptation": 0.0})
    action = _action("council_compromise", category="diplomatic")
    pressure = apply_scenario_pressure(
        world,
        pressure_rules=[
            PressureRule(
                rule_id="ring_tax",
                applies_to_categories=["diplomatic"],
                effects=ScenarioEventEffect(
                    truth_metric_effects={"ring_temptation": 0.2}
                ),
            )
        ],
        hidden_obligations=[],
        deterministic_result=DeterministicTurnResult(
            world_state=world,
            accepted_actions=[action],
        ),
    )

    assert pressure.world_state.truth_metrics["ring_temptation"] == 0.2


def _world(
    truth_metrics: dict[str, float] | None = None,
    *,
    hidden_clocks: dict[str, float] | None = None,
) -> WorldStateV2:
    return WorldStateV2(
        scenario_id="test",
        truth_metrics=truth_metrics or {},
        hidden_clocks=hidden_clocks or {},
        actors={
            "player": EntityState(
                entity_id="player",
                name="Player",
                entity_type=EntityType.PLAYER_FACTION,
                role="Player",
            )
        },
    )


def _action(
    action_id: str,
    *,
    category: str = "diplomatic",
    capability_id: str | None = None,
) -> ActionPackage:
    return ActionPackage(
        actor_id="player",
        action_id=action_id,
        capability_id=capability_id,
        channel=SignalChannel.PRIVATE_DIPLOMATIC,
        intent_summary="Act.",
        metadata={"action_category": category},
    )
