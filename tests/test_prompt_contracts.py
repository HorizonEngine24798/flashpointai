from __future__ import annotations

import pytest
from pydantic import ValidationError

from crisis_room.agents.context import build_visible_context
from crisis_room.agents.faction import FactionAgent, NESTED_LLM_CONTEXT_LIMIT
from crisis_room.app.turn_orchestrator import TurnOrchestrator
from crisis_room.config.settings import LlamaCppSettings
from crisis_room.llm.contracts import FakeLLMClient
from crisis_room.llm.llama_cpp_client import LlamaCppServerClient
from crisis_room.llm.task_contracts import (
    AdvisorCouncilResponse,
    AdvisorResponse,
    BackchannelCounterpartResponse,
    EventCandidate,
    EventCreatorResponse,
    FactionDecision,
    FactionTurnResponse,
    IntentCompilation,
    InternalDebate,
    InternationalPressure,
    MultiIntentCompilation,
    PerceptionUpdate,
    SignalDistortionResponse,
)
from crisis_room.scenario.schema import build_cuban_missile_crisis_1962_scenario
from crisis_room.state.advisors import AdvisorBelief
from crisis_room.state.events import EventChoiceOption, ScenarioEventChoiceRecord, ScenarioEventRecord
from crisis_room.state.signals import SignalChannel


GAMEPLAY_REQUEST_EXPECTATIONS = [
    (
        "dialogue.us_excomm.advisor_response",
        "AdvisorCouncilResponse",
        1400,
        AdvisorCouncilResponse,
    ),
    (
        "gamemaster.us_excomm.intent_compilation",
        "MultiIntentCompilation",
        1800,
        MultiIntentCompilation,
    ),
    ("faction.soviet_presidium.turn", "FactionTurnResponse", 2600, FactionTurnResponse),
    ("faction.cuba.turn", "FactionTurnResponse", 2600, FactionTurnResponse),
    ("faction.nato_allies.turn", "FactionTurnResponse", 2600, FactionTurnResponse),
    (
        "international.international.pressure",
        "InternationalPressure",
        1300,
        InternationalPressure,
    ),
    (
        "event_creator.event_creator.media_event_turn",
        "EventCreatorResponse",
        1800,
        EventCreatorResponse,
    ),
]


def test_gameplay_llm_requests_are_schema_guided_and_bounded() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=51)
    fake_llm = FakeLLMClient(_turn_responses())
    orchestrator = TurnOrchestrator(
        action_catalog=scenario.action_catalog,
        capabilities=scenario.capabilities,
        llm_client=fake_llm,
    )

    orchestrator.run_turn(
        world,
        player_entity_id="us_excomm",
        player_message="How do we keep an off-ramp open?",
        player_intent="ACTION open a private Kremlin backchannel for reciprocal restraint",
        scenario_notes=["Keep the Cuba scenario grounded in visible pressure."],
    )

    requests = [call.request for call in fake_llm.calls]
    gameplay_requests = [
        request for request in requests if not request.label.startswith("info_channel.")
    ]
    distortion_requests = [
        request for request in requests if request.label.startswith("info_channel.")
    ]
    assert [request.label for request in gameplay_requests] == [
        label for label, _, _, _ in GAMEPLAY_REQUEST_EXPECTATIONS
    ]

    client = LlamaCppServerClient(
        LlamaCppSettings(manage_server=False, max_new_tokens=4096)
    )
    try:
        for request, (_, schema_name, max_tokens, response_model) in zip(
            gameplay_requests,
            GAMEPLAY_REQUEST_EXPECTATIONS,
            strict=True,
        ):
            prompt_text = "\n".join(message.content for message in request.messages)
            assert request.response_schema_name == schema_name
            assert request.temperature == 0.2
            assert request.top_p == 0.9
            assert request.max_tokens == max_tokens
            assert "Return exactly one JSON object" in prompt_text
            assert "Contract guidance:" in prompt_text
            assert f"{schema_name} contract:" in prompt_text

            payload = client.build_payload(request, response_model)
            response_format = payload["response_format"]
            assert response_format["type"] == "json_schema"
            assert response_format["json_schema"]["name"] == schema_name
            assert payload["json_schema"] == response_format["json_schema"]["schema"]
            assert payload["temperature"] == 0.2
            assert payload["top_p"] == 0.9
            assert payload["max_tokens"] == max_tokens
        for request in distortion_requests:
            prompt_text = "\n".join(message.content for message in request.messages)
            assert request.response_schema_name == "SignalDistortionResponse"
            assert request.max_tokens == 350
            assert "SignalDistortionResponse contract:" in prompt_text
            payload = client.build_payload(request, SignalDistortionResponse)
            response_format = payload["response_format"]
            assert response_format["json_schema"]["name"] == "SignalDistortionResponse"
    finally:
        client.close()


def test_visible_context_limits_timelines_inbox_and_action_catalog() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=52)
    for index in range(5):
        world.append_public(f"Public update {index}", f"Public summary {index}")

    context = build_visible_context(
        world.actors["us_excomm"],
        world,
        action_catalog=scenario.action_catalog,
        capabilities=scenario.capabilities,
        timeline_limit=2,
        inbox_limit=0,
        action_catalog_limit=1,
    )

    assert [entry["title"] for entry in context["public_timeline"]] == [
        "Public update 3",
        "Public update 4",
    ]
    assert context["inbox"] == []
    assert len(context["action_catalog"]) == 1
    assert "truth_metric_effects" not in context["action_catalog"][0]
    assert context["context_limits"]["action_catalog_total"] == len(
        scenario.capabilities
    )
    assert context["context_limits"]["action_catalog_truncated"] is True

    empty_context = build_visible_context(
        world.actors["us_excomm"],
        world,
        action_catalog=scenario.action_catalog,
        capabilities=scenario.capabilities,
        timeline_limit=0,
        action_catalog_limit=0,
    )
    assert empty_context["public_timeline"] == []
    assert empty_context["entity_local_timeline"] == []
    assert empty_context["action_catalog"] == []


def test_visible_context_bounds_events_advisors_choices_and_prompt_hints() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=520)
    player_id = scenario.player_entity_id
    for index in range(5):
        world.event_history.append(
            ScenarioEventRecord(
                event_id=f"visible_event_{index}",
                title=f"Visible Event {index}",
                summary=f"Event summary {index}",
                turn_number=index + 1,
                visible_to=[player_id],
                problem_title=f"Problem {index}",
                problem_summary=f"Problem summary {index}",
                effect_summary=["truth:secret moved"],
            )
        )
        world.pending_event_choices.append(
            ScenarioEventChoiceRecord(
                choice_id=f"choice_{index}",
                event_id=f"visible_event_{index}",
                title=f"Choice Event {index}",
                prompt=f"Prompt {index}",
                turn_number=world.turn_number,
                expires_turn=world.turn_number + 1,
                visible_to=[player_id],
                options=[
                    EventChoiceOption(
                        option_id=f"option_{index}",
                        label=f"Option {index}",
                        action_id="private_diplomacy",
                        capability_id="cuba_open_kremlin_channel",
                        target_ids=["soviet_presidium"],
                        channel=SignalChannel.BACKCHANNEL,
                    )
                ],
            )
        )
    council = world.advisor_councils[player_id]
    state_advisor = council.advisors["state"]
    state_advisor.beliefs = {
        f"belief_{index}": AdvisorBelief(
            topic=f"belief_{index}",
            summary=f"Belief summary {index}",
        )
        for index in range(5)
    }
    state_advisor.recent_recommendations = ["first", "second", "third"]
    state_advisor.recent_embarrassments = ["missed signal", "late warning"]

    context = build_visible_context(
        world.actors[player_id],
        world,
        action_catalog=scenario.action_catalog,
        capabilities=scenario.capabilities,
        event_history_limit=2,
        pending_choice_limit=1,
        advisor_belief_limit=2,
        advisor_recent_note_limit=1,
        action_catalog_limit=1,
        action_prompt_hint_limit=1,
    )

    assert [event["event_id"] for event in context["recent_events"]] == [
        "visible_event_3",
        "visible_event_4",
    ]
    assert "effect_summary" not in context["recent_events"][0]
    assert [choice["choice_id"] for choice in context["pending_event_choices"]] == [
        "choice_4"
    ]
    first_advisor = context["advisor_council"]["advisors"][0]
    assert len(first_advisor["beliefs"]) == 2
    assert first_advisor["beliefs_total"] == 5
    assert first_advisor["recent_recommendations"] == ["third"]
    assert first_advisor["recent_embarrassments"] == ["late warning"]
    assert len(context["action_catalog"][0]["prompt_hints"]) == 1
    assert context["context_limits"]["event_history_limit"] == 2
    assert context["context_limits"]["pending_event_choice_limit"] == 1
    assert context["context_limits"]["advisor_belief_limit"] == 2


def test_task_contracts_reject_extra_fields_and_scalar_coercion() -> None:
    with pytest.raises(ValidationError):
        AdvisorCouncilResponse.model_validate(
            {"answer": "Use the channel.", "invented_mechanic": "free action"}
        )
    with pytest.raises(ValidationError):
        EventCandidate.model_validate(
            {
                "candidate_id": "bad_candidate",
                "kind": "chaos",
                "title": "Bad Candidate",
                "summary": "The model smuggles a string numeric.",
                "plausibility": "0.75",
            }
        )
    with pytest.raises(ValidationError):
        BackchannelCounterpartResponse.model_validate(
            {"accepted": "true", "response_text": "We are listening."}
        )
    with pytest.raises(ValidationError):
        EventCandidate.model_validate(
            {
                "candidate_id": "bad_effect_hint",
                "kind": "chaos",
                "title": "Bad Effect Hint",
                "summary": "The model smuggles a string effect delta.",
                "deterministic_effect_hints": {"public_alarm": "0.2"},
            }
        )


def test_multi_intent_contract_does_not_truncate_extra_candidates() -> None:
    candidates = [
        {
            "accepted": True,
            "action_id": "private_diplomacy",
            "capability_id": "cuba_open_kremlin_channel",
            "target_ids": ["soviet_presidium"],
            "intent_summary": f"Candidate {index}",
        }
        for index in range(4)
    ]

    compiled = MultiIntentCompilation.model_validate(
        {
            "accepted": True,
            "candidates": candidates,
        }
    )

    assert len(compiled.candidates) == 4
    assert [candidate.intent_summary for candidate in compiled.candidates] == [
        "Candidate 0",
        "Candidate 1",
        "Candidate 2",
        "Candidate 3",
    ]


def test_faction_single_turn_records_rich_outputs_without_followup_calls() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=53)
    item_count = NESTED_LLM_CONTEXT_LIMIT + 2
    fake_llm = FakeLLMClient(
        {
            "faction.soviet_presidium.perception_update": {
                "situation_summary": "The visible situation is noisy.",
                "belief_updates": [
                    {
                        "topic": f"topic_{index}",
                        "summary": f"interpretation {index}",
                        "confidence": 0.5,
                    }
                    for index in range(item_count)
                ],
                "uncertainty_notes": [f"uncertainty {index}" for index in range(item_count)],
                "memory_notes": [f"memory {index}" for index in range(item_count)],
                "priority_questions": [f"question {index}" for index in range(item_count)],
            },
            "faction.soviet_presidium.internal_debate": {
                "positions": [
                    {
                        "narrative_id": f"narrative_{index}",
                        "argument": f"argument {index}",
                        "preferred_action_id": "private_diplomacy",
                        "preferred_capability_id": "soviet_compromise_probe",
                        "target_entity_ids": ["us_excomm"],
                    }
                    for index in range(item_count)
                ],
                "synthesis": "Delay while probing for restraint.",
                "dominant_narrative_id": "narrative_0",
                "unresolved_disagreements": [
                    f"disagreement {index}" for index in range(item_count)
                ],
            },
            "faction.soviet_presidium.faction_decision": {
                "action_id": None,
                "target_ids": [],
                "intent_summary": "",
                "no_action_reason": "Wait for clearer visible information.",
            },
        }
    )

    FactionAgent(
        "soviet_presidium",
        scenario.action_catalog,
        scenario.capabilities,
    ).run_turn(
        world.actors["soviet_presidium"],
        world,
        fake_llm,
    )

    assert [call.request.label for call in fake_llm.calls] == [
        "faction.soviet_presidium.turn"
    ]
    raw_turn = fake_llm.calls[0].parsed_response
    assert isinstance(raw_turn, dict)
    assert len(raw_turn["perception_update"]["belief_updates"]) == item_count
    assert len(raw_turn["perception_update"]["uncertainty_notes"]) == item_count
    assert len(raw_turn["internal_debate"]["positions"]) == item_count
    assert len(raw_turn["internal_debate"]["unresolved_disagreements"]) == item_count


def _turn_responses() -> dict[str, object]:
    return {
        "dialogue.us_excomm.advisor_response": {
            "answer": "Keep the public line calm and test a private reciprocal pause.",
            "council_summary": "State leads, with Defense asking for credible pressure.",
            "advisor_views": [
                {
                    "advisor_id": "state",
                    "advisor_name": "State",
                    "stance": "open a quiet channel",
                    "reasoning": "It preserves off-ramp optionality.",
                    "confidence": 0.7,
                }
            ],
            "risk_warnings": ["A public threat could narrow room for compromise."],
            "suggested_capability_ids": ["cuba_open_kremlin_channel"],
            "suggested_action_ids": ["private_diplomacy"],
        },
        "gamemaster.us_excomm.intent_compilation": {
            "accepted": True,
            "action_id": "private_diplomacy",
            "capability_id": "cuba_open_kremlin_channel",
            "target_ids": ["soviet_presidium"],
            "channel": "backchannel",
            "intent_summary": "Open a private Kremlin channel for reciprocal restraint.",
            "private_rationale": "Test whether a managed pause is available.",
            "parameters": {},
        },
        "faction.soviet_presidium.perception_update": {
            "situation_summary": "The opponent appears to be probing for restraint.",
            "belief_updates": [
                {
                    "topic": "excomm intent",
                    "summary": "EXCOMM may accept a quiet reciprocal pause",
                    "confidence": 0.65,
                }
            ],
        },
        "faction.soviet_presidium.internal_debate": {
            "positions": [
                {
                    "narrative_id": "settlement",
                    "argument": "A deniable probe could protect our public posture.",
                    "preferred_action_id": "private_diplomacy",
                    "preferred_capability_id": "soviet_compromise_probe",
                    "target_entity_ids": ["us_excomm"],
                    "perceived_risk": 0.35,
                }
            ],
            "synthesis": "Probe privately while preserving public posture.",
            "dominant_narrative_id": "settlement",
        },
        "faction.soviet_presidium.faction_decision": {
            "action_id": "private_diplomacy",
            "capability_id": "soviet_compromise_probe",
            "target_ids": ["us_excomm"],
            "channel": "backchannel",
            "intent_summary": "Ask privately whether reciprocal restraint remains possible.",
            "private_rationale": "Avoid public capitulation while testing the exit.",
            "commitment_level": 0.45,
            "risk_acceptance": 0.35,
            "parameters": {},
        },
        "faction.cuba.perception_update": {
            "situation_summary": "Havana sees invasion risk in every U.S. signal.",
            "belief_updates": [
                {
                    "topic": "invasion threat",
                    "summary": "U.S. pressure could precede strikes.",
                    "confidence": 0.7,
                }
            ],
        },
        "faction.cuba.internal_debate": {
            "positions": [
                {
                    "narrative_id": "defiant",
                    "argument": "Raise readiness to deter attack.",
                    "preferred_action_id": "military_posture",
                    "preferred_capability_id": "cuba_air_defense_alert",
                    "target_entity_ids": ["us_excomm"],
                    "perceived_risk": 0.65,
                }
            ],
            "synthesis": "Alert posture is risky but politically necessary.",
            "dominant_narrative_id": "defiant",
        },
        "faction.cuba.faction_decision": {
            "action_id": "military_posture",
            "capability_id": "cuba_air_defense_alert",
            "target_ids": ["us_excomm"],
            "channel": "military",
            "intent_summary": "Raise Cuban air defense alert.",
            "private_rationale": "Deter invasion and force Cuba's position into the crisis.",
            "commitment_level": 0.7,
            "risk_acceptance": 0.62,
            "parameters": {},
        },
        "faction.nato_allies.perception_update": {
            "situation_summary": "Allies need consultation before backing the next public move.",
            "belief_updates": [
                {
                    "topic": "alliance consultation",
                    "summary": "Washington needs allied confidence.",
                    "confidence": 0.65,
                }
            ],
        },
        "faction.nato_allies.internal_debate": {
            "positions": [
                {
                    "narrative_id": "solidarity",
                    "argument": "Ask for reassurance while supporting Washington.",
                    "preferred_action_id": "private_diplomacy",
                    "preferred_capability_id": "nato_reassurance_pressure",
                    "target_entity_ids": ["us_excomm"],
                    "perceived_risk": 0.4,
                }
            ],
            "synthesis": "Private consultation can preserve public solidarity.",
            "dominant_narrative_id": "solidarity",
        },
        "faction.nato_allies.faction_decision": {
            "action_id": "private_diplomacy",
            "capability_id": "nato_reassurance_pressure",
            "target_ids": ["us_excomm"],
            "channel": "private_diplomatic",
            "intent_summary": "Ask Washington for reassurance and consultation.",
            "private_rationale": "Allied backing is stronger when allies are not surprised.",
            "commitment_level": 0.45,
            "risk_acceptance": 0.25,
            "parameters": {},
        },
        "international.international.pressure": {
            "situation_summary": "External actors are calling for visible restraint.",
            "legitimacy_concerns": ["Escalatory signals are raising public alarm."],
            "requested_restraints": ["Keep diplomatic channels open."],
            "pressure_signals": [
                {
                    "channel": "media",
                    "payload_type": "media_report",
                    "content": "International diplomats urge restraint from both sides.",
                    "visibility": "public",
                    "reliability": 0.8,
                }
            ],
        },
        "event_creator.event_creator.candidate": {
            "candidate_id": "chaos_radio_1",
            "kind": "chaos",
            "title": "Confused Radio Traffic",
            "summary": "Routine movement is misread as a warning sign.",
            "plausibility": 0.6,
            "escalation_pressure": 0.65,
            "suggested_signals": [
                {
                    "target_entity_ids": ["us_excomm"],
                    "channel": "intel",
                    "payload_type": "intel_report",
                    "content": "Intercepts suggest confused local radio traffic.",
                    "visibility": "secret",
                    "reliability": 0.55,
                }
            ],
        },
    }
