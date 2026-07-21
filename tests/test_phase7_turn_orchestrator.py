from __future__ import annotations

from crisis_room.app.turn_orchestrator import TurnOrchestrator
from crisis_room.llm.contracts import FakeLLMClient
from crisis_room.scenario.cuba import build_cuban_missile_crisis_1962_scenario
from crisis_room.state.signals import (
    PayloadType,
    Signal,
    SignalChannel,
    SignalVisibility,
)


def test_turn_orchestrator_runs_full_fake_agent_turn_without_live_llm() -> None:
    scenario = build_cuban_missile_crisis_1962_scenario()
    world = scenario.create_initial_world(rng_seed=31)
    world.pending_signals.append(
        Signal(
            signal_id="sig_due_start",
            source_entity_id="soviet_presidium",
            recipient_entity_ids=["us_excomm"],
            channel=SignalChannel.BACKCHANNEL,
            payload_type=PayloadType.BACKCHANNEL_MESSAGE,
            content="A due backchannel update reaches EXCOMM before decisions.",
            emitted_turn=0,
            intended_arrival_turn=1,
            visibility=SignalVisibility.COVERT,
            reliability=0.8,
            classification="confidential",
        )
    )
    fake_llm = FakeLLMClient(
        {
            "dialogue.us_excomm.advisor_response": {
                "answer": "Use a public line only if a private exit remains open.",
                "council_summary": "State favors a warning only with a private exit.",
                "advisor_views": [
                    {
                        "advisor_id": "state",
                        "advisor_name": "State",
                        "stance": "keep the channel alive",
                        "reasoning": "The new backchannel update creates room for a controlled warning.",
                        "confidence": 0.75,
                    }
                ],
                "risk_warnings": ["Public rhetoric can corner both sides."],
                "suggested_capability_ids": [
                    "cuba_public_withdrawal_demand",
                    "cuba_open_kremlin_channel",
                ],
                "suggested_action_ids": [
                    "public_statement",
                    "private_diplomacy",
                ],
            },
            "gamemaster.us_excomm.intent_compilation": {
                "accepted": True,
                "action_id": "public_statement",
                "capability_id": "cuba_public_withdrawal_demand",
                "target_ids": ["soviet_presidium"],
                "channel": "public",
                "intent_summary": "Demand removal of Soviet offensive missiles from Cuba.",
                "public_rationale": "Offensive missile bases in Cuba must be dismantled.",
                "notes": ["Compiled into the public demand catalog action."],
            },
            "faction.soviet_presidium.turn": {
                "perception_update": {
                    "situation_summary": "Moscow sees public pressure building.",
                    "belief_updates": [
                        {
                            "topic": "excomm intent",
                            "summary": "EXCOMM may still be testing for a reciprocal pause",
                            "confidence": 0.6,
                        }
                    ],
                },
                "internal_debate": {
                    "positions": [
                        {
                            "narrative_id": "hold_line",
                            "argument": "Do not concede under pressure.",
                            "preferred_action_id": "public_statement",
                            "preferred_capability_id": "soviet_defiance_statement",
                            "perceived_risk": 0.7,
                        },
                        {
                            "narrative_id": "settlement",
                            "argument": "Probe a private off-ramp before rhetoric hardens.",
                            "preferred_action_id": "private_diplomacy",
                            "preferred_capability_id": "soviet_compromise_probe",
                            "target_entity_ids": ["us_excomm"],
                            "perceived_risk": 0.35,
                        },
                    ],
                    "synthesis": "Preserve posture while privately testing the exit.",
                    "dominant_narrative_id": "settlement",
                },
                "decision": {
                    "action_id": "private_diplomacy",
                    "capability_id": "soviet_compromise_probe",
                    "target_ids": ["us_excomm"],
                    "channel": "backchannel",
                    "intent_summary": "Privately ask whether reciprocal restraint is still possible.",
                    "private_rationale": "A deniable probe avoids public capitulation.",
                    "commitment_level": 0.45,
                },
            },
            "faction.cuba.turn": {
                "perception_update": {
                    "situation_summary": "Havana reads U.S. pressure as possible invasion preparation.",
                    "belief_updates": [
                        {
                            "topic": "invasion threat",
                            "summary": "U.S. public pressure may precede military action.",
                            "confidence": 0.7,
                        }
                    ],
                },
                "internal_debate": {
                    "positions": [
                        {
                            "narrative_id": "defiant",
                            "argument": "Raise air defense readiness so Cuba cannot be ignored.",
                            "preferred_action_id": "military_posture",
                            "preferred_capability_id": "cuba_air_defense_alert",
                            "target_entity_ids": ["us_excomm"],
                            "perceived_risk": 0.65,
                        }
                    ],
                    "synthesis": "Visible readiness is risky but politically necessary.",
                    "dominant_narrative_id": "defiant",
                },
                "decision": {
                    "action_id": "military_posture",
                    "capability_id": "cuba_air_defense_alert",
                    "target_ids": ["us_excomm"],
                    "channel": "military",
                    "intent_summary": "Raise Cuban air defense alert against feared invasion.",
                    "private_rationale": "Deter attack and force superpowers to account for Cuba.",
                    "commitment_level": 0.7,
                },
            },
            "faction.nato_allies.turn": {
                "perception_update": {
                    "situation_summary": "Allies support Washington but worry about European spillover.",
                    "belief_updates": [
                        {
                            "topic": "alliance consultation",
                            "summary": "EXCOMM needs allied backing for a public line.",
                            "confidence": 0.68,
                        }
                    ],
                },
                "internal_debate": {
                    "positions": [
                        {
                            "narrative_id": "solidarity",
                            "argument": "Support Washington while demanding disciplined consultation.",
                            "preferred_action_id": "private_diplomacy",
                            "preferred_capability_id": "nato_reassurance_pressure",
                            "target_entity_ids": ["us_excomm"],
                            "perceived_risk": 0.42,
                        }
                    ],
                    "synthesis": "Private reassurance can strengthen public solidarity.",
                    "dominant_narrative_id": "solidarity",
                },
                "decision": {
                    "action_id": "private_diplomacy",
                    "capability_id": "nato_reassurance_pressure",
                    "target_ids": ["us_excomm"],
                    "channel": "private_diplomatic",
                    "intent_summary": "Privately ask Washington for consultation before the next public move.",
                    "private_rationale": "Alliance backing depends on not being blindsided.",
                    "commitment_level": 0.45,
                },
            },
            "international.international.pressure": {
                "situation_summary": "External actors are alarmed by the visible standoff.",
                "pressure_signals": [
                    {
                        "channel": "media",
                        "payload_type": "media_report",
                        "content": "International diplomats call for restraint over Cuba.",
                        "visibility": "public",
                        "reliability": 0.8,
                    }
                ],
            },
            "event_creator.event_creator.media_event_turn": {
                "public_brief": {
                    "headline": "Reconnaissance Confusion",
                    "summary": "A local unit misreads routine movement as a warning sign.",
                    "public_risk_read": "Visible standoff remains tense.",
                },
                "event_candidate": {
                    "candidate_id": "recon_confusion_1",
                    "kind": "chaos",
                    "title": "Reconnaissance Confusion",
                    "summary": "A local unit misreads routine movement as a warning sign.",
                    "plausibility": 0.65,
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
    orchestrator = TurnOrchestrator(
        action_catalog=scenario.action_catalog,
        capabilities=scenario.capabilities,
        llm_client=fake_llm,
    )

    result = orchestrator.run_turn(
        world,
        player_entity_id="us_excomm",
        player_message="Can we warn them without foreclosing an off-ramp?",
        player_intent="ACTION: issue a public warning against further deployments",
        scenario_notes=["Cuba 1962 should keep pressure plausible and compact."],
    )

    assert result.world_state.turn_number == 2
    assert len(result.start_routing_result.deliveries) == 1
    assert result.start_routing_result.deliveries[0].signal_id == "sig_due_start"
    dialogue_prompt = "\n".join(
        message.content for message in fake_llm.calls[0].request.messages
    )
    assert "A due backchannel update reaches EXCOMM" in dialogue_prompt
    assert result.dialogue_response is not None
    assert result.dialogue_response.suggested_capability_ids == [
        "cuba_public_withdrawal_demand",
        "cuba_open_kremlin_channel",
    ]
    assert not result.player_compilation.rejected
    assert set(result.agent_outputs) == {
        "soviet_presidium",
        "cuba",
        "nato_allies",
        "international",
    }
    assert result.agent_outputs["soviet_presidium"].action_package is not None
    assert result.event_output is not None
    assert result.event_output.perception_summary.startswith("Reconnaissance Confusion")
    media_entry = result.event_output.public_timeline_delta[0]
    assert media_entry.source == "event_creator"
    assert media_entry.title == "Reconnaissance Confusion"
    assert any(
        entry.entry_id == media_entry.entry_id
        for entry in result.world_state.public_timeline.entries
    )
    assert result.aftermath_report.media_headlines == [
        f"{media_entry.title}: {media_entry.summary}"
    ]
    assert {
        action.mechanical_id for action in result.deterministic_result.accepted_actions
    } == {
        "cuba_public_withdrawal_demand",
        "soviet_compromise_probe",
        "cuba_air_defense_alert",
        "nato_reassurance_pressure",
    }
    assert len(result.final_routing_result.deliveries) >= 8
    assert result.world_state.pending_signals == []
    assert result.world_state.actors["us_excomm"].inbox
    assert result.world_state.actors["soviet_presidium"].resources["diplomatic_flexibility"] == 2
    assert result.world_state.actors["us_excomm"].resources["political_capital"] == 6
    assert result.debug_transcript.rendered_text.startswith("ORCHESTRATED TURN DEBUG")
    assert "media headline: Reconnaissance Confusion" in result.debug_transcript.rendered_text
    assert result.debug_transcript.model_dump(mode="json")["scenario_id"] == (
        "cuban_missile_crisis_1962"
    )
