from __future__ import annotations

import pytest

from crisis_room.agents.dialogue_engine import DialogueEngineAgent
from crisis_room.app.advisor_updates import update_advisor_council
from crisis_room.app.tui import _print_advisors
from crisis_room.config.gameplay import ADVISOR_DELTA_CLAMP
from crisis_room.engine.adjudication import DeterministicTurnResult
from crisis_room.llm.contracts import FakeLLMClient
from crisis_room.llm.scripted_client import ScriptedLLMClient
from crisis_room.llm.task_contracts import AdvisorCouncilResponse
from crisis_room.scenario.schema import build_cuban_missile_crisis_1962_scenario


def test_advisor_council_response_rejects_invented_advisors() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=71)
    fake_llm = FakeLLMClient(
        {
            "dialogue.us_excomm.advisor_response": {
                "answer": "Invent a new voice.",
                "advisor_views": [
                    {
                        "advisor_id": "space_force",
                        "advisor_name": "Space Force",
                        "stance": "invented",
                        "reasoning": "This advisor is not in the scenario council.",
                    }
                ],
                "suggested_capability_ids": ["cuba_open_kremlin_channel"],
            }
        }
    )

    with pytest.raises(ValueError, match="unknown advisor_id"):
        DialogueEngineAgent(
            action_catalog=scenario.action_catalog,
            capabilities=scenario.capabilities,
        ).respond_to_player(
            world,
            player_entity_id=scenario.player_entity_id,
            player_message="Who should be in the room?",
            llm_client=fake_llm,
        )


def test_proposed_advisor_deltas_are_clamped_in_update_step() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=72)
    before = world.model_copy(deep=True)
    response = AdvisorCouncilResponse.model_validate(
        {
            "answer": "State grows more confident in the player's off-ramp framing.",
            "advisor_views": [],
            "proposed_advisor_deltas": [
                {
                    "advisor_id": "state",
                    "trust_player_delta": 1.0,
                    "urgency_delta": -1.0,
                    "trust_channel_deltas": {"backchannel": 1.0},
                    "memory_notes": ["The player explicitly asked for an off-ramp."],
                    "reasons": ["The answer reinforced a diplomatic path."],
                }
            ],
        }
    )

    update = update_advisor_council(
        world,
        before_world_state=before,
        player_entity_id=scenario.player_entity_id,
        action_catalog=scenario.action_catalog,
        capabilities=scenario.capabilities,
        deterministic_result=DeterministicTurnResult(world_state=world),
        council_response=response,
    )

    assert update is not None
    delta = next(item for item in update.deltas if item.advisor_id == "state")
    assert delta.trust_player_delta == ADVISOR_DELTA_CLAMP
    assert delta.urgency_delta == -ADVISOR_DELTA_CLAMP
    assert delta.trust_channel_deltas["backchannel"] == ADVISOR_DELTA_CLAMP
    state = world.advisor_councils[scenario.player_entity_id].advisors["state"]
    assert state.trust_player == before.advisor_councils[
        scenario.player_entity_id
    ].advisors["state"].trust_player + ADVISOR_DELTA_CLAMP


def test_advisor_display_keeps_numbers_debug_only(capsys: pytest.CaptureFixture[str]) -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=73)

    _print_advisors(world, scenario.player_entity_id)
    normal = capsys.readouterr().out
    assert "%" not in normal
    assert "steady trust" in normal or "strong trust" in normal

    _print_advisors(world, scenario.player_entity_id, debug_mode=True)
    debug = capsys.readouterr().out
    assert "%" in debug
    assert "trust 62%" in debug


def test_memory_embarrassment_and_trust_shape_scripted_advice() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=74)
    council = world.advisor_councils[scenario.player_entity_id]
    council.advisors["state"].recent_recommendations = ["Do not humiliate Moscow."]
    council.advisors["defense"].trust_advisors["state"] = 0.8
    council.advisors["intelligence"].recent_embarrassments = [
        "An earlier readiness estimate was overstated."
    ]

    response = DialogueEngineAgent(
        action_catalog=scenario.action_catalog,
        capabilities=scenario.capabilities,
    ).respond_to_player(
        world,
        player_entity_id=scenario.player_entity_id,
        player_message="How do we keep an off-ramp open?",
        llm_client=ScriptedLLMClient(),
    )

    by_id = {view.advisor_id: view for view in response.advisor_views}
    assert "last recommendation" in by_id["state"].reasoning
    assert "can live with State" in by_id["defense"].reasoning
    assert "last embarrassment" in by_id["intelligence"].reasoning
    assert response.suggested_capability_ids
