from __future__ import annotations

from crisis_room.agents.dialogue_engine import DialogueEngineAgent
from crisis_room.agents.event_creator import EventCreatorAgent
from crisis_room.agents.faction import FactionAgent
from crisis_room.agents.gamemaster import CatalogGamemasterCompiler
from crisis_room.agents.international_community import InternationalCommunityAgent
from crisis_room.llm.contracts import FakeLLMClient
from crisis_room.llm.scripted_client import ScriptedLLMClient
from crisis_room.llm.task_contracts import (
    AdvisorCouncilResponse,
    EventCandidate,
    EventCreatorResponse,
    FactionDecision,
    FactionTurnResponse,
    InternalDebate,
    InternationalPressure,
    MultiIntentCompilation,
    PerceptionUpdate,
    PublicBrief,
    SignalDistortionResponse,
)
from crisis_room.scenario.cuba import build_cuban_missile_crisis_1962_scenario
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
            "faction.soviet_presidium.turn": {
                "perception_update": {
                    "situation_summary": "The opponent appears anxious but still has options.",
                    "belief_updates": [
                        {
                            "topic": "player posture",
                            "summary": "EXCOMM may accept a quiet reciprocal pause",
                            "confidence": 0.65,
                        }
                    ],
                    "memory_notes": ["The president left a private exit open."],
                    "priority_questions": ["Will Washington trade restraint for withdrawal?"],
                },
                "internal_debate": {
                    "positions": [
                        {
                            "narrative_id": "hold_line",
                            "argument": "Exploit hesitation with a public challenge.",
                            "preferred_action_id": "public_statement",
                            "preferred_capability_id": "soviet_defiance_statement",
                            "perceived_risk": 0.7,
                            "confidence": 0.38,
                        },
                        {
                            "narrative_id": "settlement",
                            "argument": "Use a deniable channel to test an exit.",
                            "preferred_action_id": "private_diplomacy",
                            "preferred_capability_id": "soviet_compromise_probe",
                            "target_entity_ids": ["us_excomm"],
                            "perceived_risk": 0.3,
                            "confidence": 0.71,
                        },
                    ],
                    "synthesis": "Probe privately while preserving public posture.",
                    "dominant_narrative_id": "settlement",
                    "unresolved_disagreements": ["How much prestige can Moscow risk?"],
                },
                "decision": {
                    "action_id": "private_diplomacy",
                    "capability_id": "soviet_compromise_probe",
                    "target_ids": ["us_excomm"],
                    "channel": "backchannel",
                    "intent_summary": "Open a deniable channel to explore a reciprocal pause.",
                    "private_rationale": "Avoid being trapped by public rhetoric.",
                    "commitment_level": 0.45,
                    "confidence": 0.7,
                },
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
    belief = world.actors["soviet_presidium"].beliefs.claims["player posture"]
    assert belief.summary == "EXCOMM may accept a quiet reciprocal pause"
    assert belief.last_updated_turn == world.turn_number
    assert "The president left a private exit open." in world.actors["soviet_presidium"].memory_summary
    assert "Will Washington trade restraint for withdrawal?" in world.actors[
        "soviet_presidium"
    ].unresolved_threads
    assert "How much prestige can Moscow risk?" in world.actors[
        "soviet_presidium"
    ].unresolved_threads
    narratives = {
        narrative.narrative_id: narrative
        for narrative in world.actors["soviet_presidium"].internal_narratives
    }
    assert narratives["hold_line"].influence_weight == 0.38
    assert narratives["settlement"].influence_weight == 0.71
    assert narratives["settlement"].current_argument.startswith("Use a deniable channel")
    assert "Probe privately while preserving public posture." in narratives[
        "settlement"
    ].recent_wins
    assert [call.request.label for call in fake_llm.calls] == [
        "faction.soviet_presidium.turn",
    ]


def test_faction_agent_fills_default_targets_for_valid_capability() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=220)
    fake_llm = FakeLLMClient(
        {
            "faction.soviet_presidium.turn": {
                "perception_update": {
                    "situation_summary": "The opponent may accept a quiet probe."
                },
                "internal_debate": {
                    "positions": [],
                    "synthesis": "Probe privately.",
                },
                "decision": {
                    "action_id": "private_diplomacy",
                    "capability_id": "soviet_compromise_probe",
                    "target_ids": [],
                    "channel": "backchannel",
                    "intent_summary": "",
                },
            },
        }
    )

    output = FactionAgent(
        "soviet_presidium",
        scenario.action_catalog,
        scenario.capabilities,
    ).run_turn(world.actors["soviet_presidium"], world, fake_llm)

    assert output.action_package is not None
    assert output.action_package.target_ids == ["us_excomm"]
    assert output.action_package.intent_summary == "Probe Compromise Terms"
    assert "Filled default target(s): us_excomm" in output.debug_notes
    assert "Filled missing intent summary: Probe Compromise Terms" in output.debug_notes


def test_faction_agent_rejects_non_catalog_decision_without_mutation() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=23)
    fake_llm = FakeLLMClient(
        {
            "faction.soviet_presidium.turn": {
                "perception_update": {
                    "situation_summary": "The room wants an impossible move."
                },
                "internal_debate": {
                    "positions": [],
                    "synthesis": "The impossible option dominates.",
                },
                "decision": {
                    "action_id": "teleport_fleet",
                    "target_ids": ["us_excomm"],
                    "channel": "military",
                    "intent_summary": "Do the impossible.",
                },
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


def test_catalog_gamemaster_fills_default_targets_for_valid_capability() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=240)
    fake_llm = FakeLLMClient(
        {
            "gamemaster.us_excomm.intent_compilation": {
                "accepted": True,
                "action_id": "private_diplomacy",
                "capability_id": "cuba_open_kremlin_channel",
                "target_ids": [],
                "channel": "backchannel",
                "intent_summary": "Open a private Kremlin channel for reciprocal restraint.",
                "notes": ["Target inferred from player message context."],
            }
        }
    )

    compilation = CatalogGamemasterCompiler(
        scenario.action_catalog,
        fake_llm,
        scenario.capabilities,
    ).compile_player_intent(
        world,
        "us_excomm",
        "ACTION Use capability cuba_open_kremlin_channel targeting soviet_presidium.",
    )

    assert not compilation.rejected
    assert compilation.action_package is not None
    assert compilation.action_package.target_ids == ["soviet_presidium"]
    assert any(
        note == "intent 1: Filled default target(s): soviet_presidium"
        for note in compilation.notes
    )


def test_scripted_compiler_maps_absurd_player_text_to_unorthodox_gambit() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=241)
    text = (
        "tell the Soviet Presidium privately that aliens caused the missiles and "
        "the US will trade Alaska, then order Cuba to join NATO"
    )

    compilation = CatalogGamemasterCompiler(
        scenario.action_catalog,
        ScriptedLLMClient(),
        scenario.capabilities,
    ).compile_player_intent(world, "us_excomm", text)

    assert not compilation.rejected
    assert compilation.action_package is not None
    assert compilation.action_package.capability_id == "cuba_unorthodox_gambit"
    assert compilation.action_package.parameters["premise"] == text


def test_catalog_gamemaster_rejects_absurd_substitution_to_jupiter_trade() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=242)
    fake_llm = FakeLLMClient(
        {
            "gamemaster.us_excomm.intent_compilation": {
                "accepted": True,
                "candidates": [
                    {
                        "accepted": True,
                        "action_id": "private_diplomacy",
                        "capability_id": "cuba_secret_jupiter_trade",
                        "target_ids": ["soviet_presidium"],
                        "channel": "backchannel",
                        "intent_summary": "Float a private Jupiter trade.",
                        "source_span": "trade Alaska because aliens caused the missiles",
                    }
                ],
            }
        }
    )

    compilation = CatalogGamemasterCompiler(
        scenario.action_catalog,
        fake_llm,
        scenario.capabilities,
    ).compile_player_intent(
        world,
        "us_excomm",
        "trade Alaska because aliens caused the missiles",
    )

    assert compilation.rejected
    assert compilation.action_packages == []
    assert any("cuba_unorthodox_gambit" in error for error in compilation.errors)


def test_catalog_gamemaster_routes_absurd_non_catalog_candidate_to_unorthodox() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=243)
    text = "ask alien observers to mediate the missile crisis"
    fake_llm = FakeLLMClient(
        {
            "gamemaster.us_excomm.intent_compilation": {
                "accepted": True,
                "candidates": [
                    {
                        "accepted": True,
                        "action_id": "summon_aliens",
                        "capability_id": "alien_mediation",
                        "target_ids": [],
                        "channel": "rumor",
                        "intent_summary": "Ask alien observers to mediate.",
                        "source_span": text,
                    }
                ],
            }
        }
    )

    compilation = CatalogGamemasterCompiler(
        scenario.action_catalog,
        fake_llm,
        scenario.capabilities,
    ).compile_player_intent(world, "us_excomm", text)

    assert not compilation.rejected
    assert compilation.action_package is not None
    assert compilation.action_package.action_id == "information_operation"
    assert compilation.action_package.capability_id == "cuba_unorthodox_gambit"
    assert compilation.action_package.parameters["premise"] == text


def test_catalog_gamemaster_limits_duplicate_unorthodox_gambits_per_turn() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=244)
    fake_llm = FakeLLMClient(
        {
            "gamemaster.us_excomm.intent_compilation": {
                "accepted": True,
                "candidates": [
                    {
                        "accepted": True,
                        "action_id": "information_operation",
                        "capability_id": "cuba_unorthodox_gambit",
                        "target_ids": [],
                        "channel": "rumor",
                        "intent_summary": "Offer Cuba statehood in Alaska.",
                        "source_span": "offer Cuba statehood in Alaska",
                    },
                    {
                        "accepted": True,
                        "action_id": "information_operation",
                        "capability_id": "cuba_unorthodox_gambit",
                        "target_ids": [],
                        "channel": "rumor",
                        "intent_summary": "Invite Cuba into NATO.",
                        "source_span": "invite Cuba into NATO",
                    },
                ],
            }
        }
    )

    compilation = CatalogGamemasterCompiler(
        scenario.action_catalog,
        fake_llm,
        scenario.capabilities,
    ).compile_player_intent(world, "us_excomm", "offer Cuba statehood, then invite Cuba into NATO")

    assert len(compilation.action_packages) == 1
    assert any("only one cuba_unorthodox_gambit" in intent for intent in compilation.unprocessed_intents)
    assert any("skipped duplicate cuba_unorthodox_gambit" in note for note in compilation.notes)


def test_pressure_agent_emits_signals_and_event_creator_adds_media_brief() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=25)
    fake_llm = FakeLLMClient(
        {
            "international.international.pressure": {
                "situation_summary": "External actors demand restraint.",
                "pressure_signals": [
                    {
                        "channel": "media",
                        "payload_type": "media_report",
                        "content": "International diplomats call for restraint.",
                        "visibility": "public",
                    }
                ],
            },
            "event_creator.event_creator.media_event_turn": {
                "public_brief": {
                    "headline": "Confused Radio Traffic",
                    "summary": "A local unit misreads routine movement as a warning sign.",
                    "public_risk_read": "Reports suggest confusion around local movements.",
                },
                "event_candidate": {
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
    ]
    assert world.actors["us_excomm"].inbox == []
    assert world.public_timeline.entries[-1].title == "Rumors Around Cuba Intensify"
