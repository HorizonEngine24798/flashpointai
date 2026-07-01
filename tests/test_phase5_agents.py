from __future__ import annotations

from crisis_room.agents.dialogue_engine import DialogueEngineAgent
from crisis_room.agents.event_creator import EventCreatorAgent
from crisis_room.agents.faction import FactionAgent
from crisis_room.agents.gamemaster import CatalogGamemasterCompiler
from crisis_room.agents.international_community import InternationalCommunityAgent
from crisis_room.llm.contracts import FakeLLMClient
from crisis_room.llm.task_contracts import (
    AARSummary,
    AdvisorCouncilResponse,
    AdvisorResponse,
    EventCandidate,
    EventCreatorResponse,
    FactionDecision,
    FactionTurnResponse,
    IntentCompilation,
    InternalDebate,
    InternationalPressure,
    MultiIntentCompilation,
    PerceptionUpdate,
    PublicBrief,
    SignalDistortionResponse,
)
from crisis_room.scenario.schema import build_cuban_missile_crisis_1962_scenario
from crisis_room.state.signals import PayloadType, SignalChannel, SignalVisibility


def test_phase5_task_contracts_validate_fake_json() -> None:
    PerceptionUpdate.model_validate(
        {
            "situation_summary": "Signals are noisy but pressure is rising.",
            "belief_updates": [{"topic": "rival intent", "summary": "still probing"}],
        }
    )
    InternalDebate.model_validate(
        {
            "positions": [
                {
                    "narrative_id": "resolve",
                    "argument": "Credible pressure is needed.",
                    "preferred_action_id": "public_statement",
                    "preferred_capability_id": "cuba_public_withdrawal_demand",
                }
            ],
            "synthesis": "Use pressure with a private exit.",
        }
    )
    FactionDecision.model_validate(
        {
            "action_id": "private_diplomacy",
            "capability_id": "cuba_open_kremlin_channel",
            "target_ids": ["soviet_presidium"],
            "channel": "backchannel",
            "intent_summary": "Open a quiet reciprocal pause channel.",
        }
    )
    FactionTurnResponse.model_validate(
        {
            "perception_update": {
                "situation_summary": "Signals are noisy but pressure is rising.",
            },
            "internal_debate": {
                "positions": [
                    {
                        "narrative_id": "resolve",
                        "argument": "Credible pressure is needed.",
                    }
                ],
                "synthesis": "Use pressure with a private exit.",
            },
            "decision": {
                "action_id": "private_diplomacy",
                "capability_id": "cuba_open_kremlin_channel",
                "target_ids": ["soviet_presidium"],
                "channel": "backchannel",
                "intent_summary": "Open a quiet reciprocal pause channel.",
            },
        }
    )
    AdvisorCouncilResponse.model_validate(
        {
            "answer": "The room is split.",
            "advisor_views": [
                {
                    "advisor_id": "state",
                    "advisor_name": "State",
                    "stance": "probe quietly",
                    "reasoning": "It preserves off-ramps.",
                }
            ],
        }
    )
    IntentCompilation.model_validate(
        {
            "accepted": True,
            "action_id": "public_statement",
            "capability_id": "cuba_public_withdrawal_demand",
            "target_ids": ["soviet_presidium"],
            "channel": "public",
            "intent_summary": "Warn publicly.",
        }
    )
    MultiIntentCompilation.model_validate(
        {
            "accepted": True,
            "candidates": [
                {
                    "accepted": True,
                    "action_id": "public_statement",
                    "capability_id": "cuba_public_withdrawal_demand",
                    "target_ids": ["soviet_presidium"],
                    "channel": "public",
                    "intent_summary": "Warn publicly.",
                }
            ],
        }
    )
    EventCandidate.model_validate(
        {
            "candidate_id": "media_leak_1",
            "kind": "media_leak",
            "title": "Leak Intensifies Public Pressure",
            "summary": "A partial report circulates internationally.",
        }
    )
    InternationalPressure.model_validate(
        {
            "situation_summary": "External actors are alarmed.",
            "pressure_signals": [
                {
                    "channel": "media",
                    "payload_type": "media_report",
                    "content": "Diplomats call for restraint.",
                }
            ],
        }
    )
    PublicBrief.model_validate(
        {
            "headline": "Crisis Diplomacy Continues",
            "summary": "Governments report ongoing consultations.",
        }
    )
    SignalDistortionResponse.model_validate(
        {
            "observed_content": "The report arrives garbled and overstates the warning.",
            "distortion_note": "Intent was hardened by channel noise.",
        }
    )
    EventCreatorResponse.model_validate(
        {
            "public_brief": {
                "headline": "Crisis Diplomacy Continues",
                "summary": "Governments report ongoing consultations.",
            },
            "event_candidate": {
                "candidate_id": "media_leak_1",
                "kind": "media_leak",
                "title": "Leak Intensifies Public Pressure",
                "summary": "A partial report circulates internationally.",
            },
            "major_event_relevant": True,
        }
    )
    AARSummary.model_validate(
        {
            "outcome_summary": "The crisis stabilized.",
            "turning_points": [
                {
                    "turn": 2,
                    "title": "Backchannel Opened",
                    "causal_summary": "A private message reduced misread risk.",
                }
            ],
        }
    )


def test_dialogue_engine_uses_player_visible_context_without_truth_leak() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=21)
    world.append_omniscient("Hidden Deployment", "SECRET WAR PLAN moves at dawn.")
    fake_llm = FakeLLMClient(
        {
            "dialogue.us_excomm.advisor_response": {
                "answer": "The strongest move is a private probe before public escalation.",
                "council_summary": "State favors a private probe before a public line.",
                "advisor_views": [
                    {
                        "advisor_id": "state",
                        "advisor_name": "State",
                        "stance": "backchannel first",
                        "reasoning": "It tests intent without public lock-in.",
                        "confidence": 0.7,
                    }
                ],
                "risk_warnings": ["A public warning may narrow exit options."],
                "suggested_capability_ids": ["cuba_open_kremlin_channel"],
                "suggested_action_ids": ["private_diplomacy"],
                "visible_context_limits": ["No direct confirmation of rival red lines."],
            }
        }
    )
    agent = DialogueEngineAgent(
        action_catalog=scenario.action_catalog,
        capabilities=scenario.capabilities,
    )

    response = agent.respond_to_player(
        world,
        player_entity_id="us_excomm",
        player_message="What is the least escalatory serious move?",
        llm_client=fake_llm,
    )

    assert response.suggested_capability_ids == ["cuba_open_kremlin_channel"]
    prompt_text = "\n".join(message.content for message in fake_llm.calls[0].request.messages)
    assert "Rumors Around Cuba Intensify" in prompt_text
    assert "SECRET WAR PLAN" not in prompt_text
    assert "truth_metrics" not in prompt_text
    assert "hidden_clocks" not in prompt_text


def test_faction_agent_runs_debate_and_returns_valid_catalog_action() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=22)
    fake_llm = FakeLLMClient(
        {
            "faction.soviet_presidium.perception_update": {
                "situation_summary": "The opponent appears anxious but still has options.",
                "belief_updates": [
                    {
                        "topic": "player posture",
                        "summary": "EXCOMM may accept a quiet reciprocal pause",
                        "confidence": 0.65,
                    }
                ],
            },
            "faction.soviet_presidium.internal_debate": {
                "positions": [
                    {
                        "narrative_id": "push",
                        "argument": "Exploit hesitation with a public challenge.",
                        "preferred_action_id": "public_statement",
                        "preferred_capability_id": "soviet_defiance_statement",
                        "perceived_risk": 0.7,
                    },
                    {
                        "narrative_id": "exit",
                        "argument": "Use a deniable channel to test an exit.",
                        "preferred_action_id": "private_diplomacy",
                        "preferred_capability_id": "soviet_compromise_probe",
                        "target_entity_ids": ["us_excomm"],
                        "perceived_risk": 0.3,
                    },
                ],
                "synthesis": "Probe privately while preserving public posture.",
                "dominant_narrative_id": "exit",
            },
            "faction.soviet_presidium.faction_decision": {
                "action_id": "private_diplomacy",
                "capability_id": "soviet_compromise_probe",
                "target_ids": ["us_excomm"],
                "channel": "backchannel",
                "intent_summary": "Open a deniable channel to explore a reciprocal pause.",
                "private_rationale": "Avoid being trapped by public rhetoric.",
                "commitment_level": 0.45,
                "risk_acceptance": 0.35,
                "confidence": 0.7,
            },
        }
    )
    agent = FactionAgent("soviet_presidium", scenario.action_catalog, scenario.capabilities)

    output = agent.run_turn(world.actors["soviet_presidium"], world, fake_llm)

    assert output.perception_summary.startswith("The opponent appears anxious")
    assert output.action_package is not None
    assert output.action_package.actor_id == "soviet_presidium"
    assert output.action_package.action_id == "private_diplomacy"
    assert output.action_package.capability_id == "soviet_compromise_probe"
    assert output.action_package.target_ids == ["us_excomm"]
    assert output.action_package.channel == SignalChannel.BACKCHANNEL
    assert output.action_package.submitted_turn == world.turn_number
    assert world.actors["soviet_presidium"].resources["diplomatic_flexibility"] == 3
    assert [call.request.label for call in fake_llm.calls] == [
        "faction.soviet_presidium.turn",
    ]


def test_faction_agent_rejects_non_catalog_decision_without_mutation() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=23)
    fake_llm = FakeLLMClient(
        {
            "faction.soviet_presidium.perception_update": {
                "situation_summary": "The room wants an impossible move."
            },
            "faction.soviet_presidium.internal_debate": {
                "positions": [],
                "synthesis": "The impossible option dominates.",
            },
            "faction.soviet_presidium.faction_decision": {
                "action_id": "teleport_fleet",
                "target_ids": ["us_excomm"],
                "channel": "military",
                "intent_summary": "Do the impossible.",
            },
        }
    )

    output = FactionAgent(
        "soviet_presidium",
        scenario.action_catalog,
        scenario.capabilities,
    ).run_turn(
        world.actors["soviet_presidium"],
        world,
        fake_llm,
    )

    assert output.action_package is None
    assert output.debug_notes == ["decision referenced non-catalog action: teleport_fleet"]
    assert world.pending_actions == []


def test_catalog_gamemaster_compiler_validates_llm_intent_against_engine() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=24)
    fake_llm = FakeLLMClient(
        {
            "gamemaster.us_excomm.intent_compilation": {
                "accepted": True,
                "action_id": "public_statement",
                "capability_id": "cuba_public_withdrawal_demand",
                "target_ids": ["soviet_presidium"],
                "channel": "public",
                "intent_summary": "Demand removal of Soviet offensive missiles from Cuba.",
                "public_rationale": "Offensive missile bases in Cuba must be dismantled.",
                "notes": ["Mapped the player's public demand to the catalog action."],
            }
        }
    )
    compiler = CatalogGamemasterCompiler(
        scenario.action_catalog,
        fake_llm,
        scenario.capabilities,
    )

    compilation = compiler.compile_player_intent(
        world,
        "us_excomm",
        "ACTION: announce that further deployments will have consequences",
    )

    assert not compilation.rejected
    assert compilation.action_package is not None
    assert compilation.action_package.action_id == "public_statement"
    assert compilation.action_package.capability_id == "cuba_public_withdrawal_demand"
    assert compilation.action_package.channel == SignalChannel.PUBLIC
    assert compilation.notes == ["Mapped the player's public demand to the catalog action."]


def test_pressure_agent_emits_signals_and_event_creator_adds_media_brief() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=25)
    fake_llm = FakeLLMClient(
        {
            "international.international.pressure": {
                "situation_summary": "External actors demand restraint.",
                "legitimacy_concerns": ["Public alarm is rising."],
                "pressure_signals": [
                    {
                        "channel": "media",
                        "payload_type": "media_report",
                        "content": "International diplomats call for restraint.",
                        "visibility": "public",
                    }
                ],
            },
            "event_creator.event_creator.candidate": {
                "candidate_id": "chaos_radio_1",
                "kind": "chaos",
                "title": "Confused Radio Traffic",
                "summary": "A local unit misreads routine movement as a warning sign.",
                "plausibility": 0.6,
                "escalation_pressure": 0.7,
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
    )

    pressure_output = InternationalCommunityAgent().run_turn(
        world.actors["international"],
        world,
        fake_llm,
    )
    event_output = EventCreatorAgent().create_candidate(world, llm_client=fake_llm)

    assert len(pressure_output.emitted_signals) == 1
    assert pressure_output.emitted_signals[0].payload_type == PayloadType.MEDIA_REPORT
    assert pressure_output.emitted_signals[0].visibility == SignalVisibility.PUBLIC
    assert event_output.emitted_signals == []
    assert event_output.public_timeline_delta[0].title == "Confused Radio Traffic"
    assert [item["task"] for item in event_output.raw_llm_outputs] == [
        "event_creator_response",
        "public_brief",
        "event_candidate",
    ]
    assert world.actors["us_excomm"].inbox == []
    assert world.public_timeline.entries[-1].title == "Rumors Around Cuba Intensify"
