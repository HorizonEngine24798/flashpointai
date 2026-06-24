from __future__ import annotations

import json

from crisis_room.agents.context import build_visible_context
from crisis_room.agents.faction import FactionAgent, NESTED_LLM_CONTEXT_LIMIT
from crisis_room.app.turn_orchestrator import TurnOrchestrator
from crisis_room.config.settings import LlamaCppSettings
from crisis_room.llm.contracts import ChatRole, FakeLLMClient, LLMRequest
from crisis_room.llm.llama_cpp_client import LlamaCppServerClient
from crisis_room.llm.task_contracts import (
    AdvisorResponse,
    EventCandidate,
    FactionDecision,
    IntentCompilation,
    InternalDebate,
    InternationalPressure,
    MultiIntentCompilation,
    PerceptionUpdate,
)
from crisis_room.scenario.schema import build_cuban_missile_crisis_1962_scenario


GAMEPLAY_REQUEST_EXPECTATIONS = [
    ("dialogue.us_excomm.advisor_response", "AdvisorResponse", 1400, AdvisorResponse),
    (
        "gamemaster.us_excomm.intent_compilation",
        "MultiIntentCompilation",
        1800,
        MultiIntentCompilation,
    ),
    ("faction.soviet_presidium.perception_update", "PerceptionUpdate", 1000, PerceptionUpdate),
    ("faction.soviet_presidium.internal_debate", "InternalDebate", 1300, InternalDebate),
    ("faction.soviet_presidium.faction_decision", "FactionDecision", 1200, FactionDecision),
    ("faction.cuba.perception_update", "PerceptionUpdate", 1000, PerceptionUpdate),
    ("faction.cuba.internal_debate", "InternalDebate", 1300, InternalDebate),
    ("faction.cuba.faction_decision", "FactionDecision", 1200, FactionDecision),
    ("faction.nato_allies.perception_update", "PerceptionUpdate", 1000, PerceptionUpdate),
    ("faction.nato_allies.internal_debate", "InternalDebate", 1300, InternalDebate),
    ("faction.nato_allies.faction_decision", "FactionDecision", 1200, FactionDecision),
    (
        "international.international.pressure",
        "InternationalPressure",
        1300,
        InternationalPressure,
    ),
    ("event_creator.event_creator.candidate", "EventCandidate", 1300, EventCandidate),
]


def test_gameplay_llm_requests_are_schema_guided_and_bounded() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=51)
    fake_llm = FakeLLMClient(_turn_responses())
    orchestrator = TurnOrchestrator(
        action_catalog=scenario.action_catalog,
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
    assert [request.label for request in requests] == [
        label for label, _, _, _ in GAMEPLAY_REQUEST_EXPECTATIONS
    ]

    client = LlamaCppServerClient(
        LlamaCppSettings(manage_server=False, max_new_tokens=4096)
    )
    try:
        for request, (_, schema_name, max_tokens, response_model) in zip(
            requests,
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
        scenario.action_catalog
    )
    assert context["context_limits"]["action_catalog_truncated"] is True

    empty_context = build_visible_context(
        world.actors["us_excomm"],
        world,
        action_catalog=scenario.action_catalog,
        timeline_limit=0,
        action_catalog_limit=0,
    )
    assert empty_context["public_timeline"] == []
    assert empty_context["entity_local_timeline"] == []
    assert empty_context["action_catalog"] == []


def test_faction_followup_contexts_bound_nested_llm_outputs() -> None:
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
                        "preferred_action_id": "soviet_probe_compromise",
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

    FactionAgent("soviet_presidium", scenario.action_catalog).run_turn(
        world.actors["soviet_presidium"],
        world,
        fake_llm,
    )

    debate_context = _visible_context_from_request(fake_llm.calls[1].request)
    decision_context = _visible_context_from_request(fake_llm.calls[2].request)

    perception = debate_context["perception_update"]
    assert len(perception["belief_updates"]) == NESTED_LLM_CONTEXT_LIMIT
    assert len(perception["uncertainty_notes"]) == NESTED_LLM_CONTEXT_LIMIT
    assert perception["nested_context_limits"]["belief_updates_total"] == item_count
    assert perception["nested_context_limits"]["belief_updates_truncated"] is True

    debate = decision_context["internal_debate"]
    assert len(debate["positions"]) == NESTED_LLM_CONTEXT_LIMIT
    assert len(debate["unresolved_disagreements"]) == NESTED_LLM_CONTEXT_LIMIT
    assert debate["nested_context_limits"]["positions_total"] == item_count
    assert debate["nested_context_limits"]["positions_truncated"] is True


def _visible_context_from_request(request: LLMRequest) -> dict[str, object]:
    user_message = next(
        message.content for message in request.messages if message.role == ChatRole.USER
    )
    context_text = user_message.split("Visible context JSON:\n", 1)[1].split(
        "\n\nTask:\n",
        1,
    )[0]
    parsed = json.loads(context_text)
    assert isinstance(parsed, dict)
    return parsed


def _turn_responses() -> dict[str, object]:
    return {
        "dialogue.us_excomm.advisor_response": {
            "answer": "Keep the public line calm and test a private reciprocal pause.",
            "advisor_views": [
                {
                    "advisor_name": "State",
                    "stance": "open a quiet channel",
                    "reasoning": "It preserves off-ramp optionality.",
                    "confidence": 0.7,
                }
            ],
            "risk_warnings": ["A public threat could narrow room for compromise."],
            "suggested_action_ids": ["private_kremlin_backchannel"],
        },
        "gamemaster.us_excomm.intent_compilation": {
            "accepted": True,
            "action_id": "private_kremlin_backchannel",
            "target_ids": ["soviet_presidium"],
            "channel": "backchannel",
            "intent_summary": "Open a private Kremlin channel for reciprocal restraint.",
            "private_rationale": "Test whether a managed pause is available.",
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
                    "preferred_action_id": "soviet_probe_compromise",
                    "target_entity_ids": ["us_excomm"],
                    "perceived_risk": 0.35,
                }
            ],
            "synthesis": "Probe privately while preserving public posture.",
            "dominant_narrative_id": "settlement",
        },
        "faction.soviet_presidium.faction_decision": {
            "action_id": "soviet_probe_compromise",
            "target_ids": ["us_excomm"],
            "channel": "backchannel",
            "intent_summary": "Ask privately whether reciprocal restraint remains possible.",
            "private_rationale": "Avoid public capitulation while testing the exit.",
            "commitment_level": 0.45,
            "risk_acceptance": 0.35,
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
                    "preferred_action_id": "cuban_air_defense_alert",
                    "target_entity_ids": ["us_excomm"],
                    "perceived_risk": 0.65,
                }
            ],
            "synthesis": "Alert posture is risky but politically necessary.",
            "dominant_narrative_id": "defiant",
        },
        "faction.cuba.faction_decision": {
            "action_id": "cuban_air_defense_alert",
            "target_ids": ["us_excomm"],
            "channel": "military",
            "intent_summary": "Raise Cuban air defense alert.",
            "private_rationale": "Deter invasion and force Cuba's position into the crisis.",
            "commitment_level": 0.7,
            "risk_acceptance": 0.62,
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
                    "preferred_action_id": "nato_reassurance_request",
                    "target_entity_ids": ["us_excomm"],
                    "perceived_risk": 0.4,
                }
            ],
            "synthesis": "Private consultation can preserve public solidarity.",
            "dominant_narrative_id": "solidarity",
        },
        "faction.nato_allies.faction_decision": {
            "action_id": "nato_reassurance_request",
            "target_ids": ["us_excomm"],
            "channel": "private_diplomatic",
            "intent_summary": "Ask Washington for reassurance and consultation.",
            "private_rationale": "Allied backing is stronger when allies are not surprised.",
            "commitment_level": 0.45,
            "risk_acceptance": 0.25,
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
