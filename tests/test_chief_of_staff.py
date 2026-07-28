from __future__ import annotations

from crisis_room.app.chief_of_staff import review_chief_plan
from crisis_room.engine.actions import ActionPackage
from crisis_room.engine.adjudication import DeterministicTurnResult
from crisis_room.llm.contracts import FakeLLMClient
from crisis_room.scenario.cuba import build_cuban_missile_crisis_1962_scenario


def test_chief_plan_filters_actions_and_bounds_completion_reward() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=91)
    player_id = scenario.player_entity_id
    client = FakeLLMClient(
        [
            {
                "assessment": "initial",
                "assessment_summary": "Open with controlled leverage.",
                "objectives": ["Establish a private off-ramp."],
                "rationale": "Preserve room to maneuver.",
                "recommended_capability_ids": [
                    "invented_action",
                    "cuba_open_kremlin_channel",
                ],
                "reward_resource": "nuclear_warheads",
                "reward_reason": "Not eligible on an initial plan.",
            },
            {
                "assessment": "completed",
                "assessment_summary": "The President established the requested channel.",
                "objectives": ["Turn private contact into a controlled settlement test."],
                "rationale": "Exploit the opening without overcommitting.",
                "recommended_capability_ids": ["invented_action"],
                "reward_resource": "political_capital",
                "reward_reason": "The coherent move improved staff confidence.",
            },
        ]
    )

    first = review_chief_plan(
        world,
        player_entity_id=player_id,
        action_catalog=scenario.action_catalog,
        capabilities=scenario.capabilities,
        llm_client=client,
        action_budget=2,
        review_turn=1,
    )
    assert not first.error
    assert world.chief_plan is not None
    assert world.chief_plan.recommended_capability_ids == ["cuba_open_kremlin_channel"]
    assert not world.chief_plan.awards

    before = world.actors[player_id].resources["political_capital"]
    action = ActionPackage(
        actor_id=player_id,
        action_id="private_diplomacy",
        capability_id="cuba_open_kremlin_channel",
        target_ids=["soviet_presidium"],
        intent_summary="Open the private channel.",
    )
    second = review_chief_plan(
        world,
        player_entity_id=player_id,
        action_catalog=scenario.action_catalog,
        capabilities=scenario.capabilities,
        llm_client=client,
        action_budget=2,
        review_turn=2,
        deterministic_result=DeterministicTurnResult(
            world_state=world,
            accepted_actions=[action],
        ),
    )

    assert world.actors[player_id].resources["political_capital"] == before + 1
    assert world.chief_plan.awards[-1].after == before + 1
    assert world.chief_plan.completed_plan_ids == ["chief_plan_1_1"]
    assert "invented_action" not in world.chief_plan.recommended_capability_ids
    assert any("Political Capital" in line and "+1" in line for line in second.update_lines)
