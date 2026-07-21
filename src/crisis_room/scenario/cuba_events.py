from __future__ import annotations

from crisis_room.scenario.events import (
    ScenarioEventChoiceDefinition,
    ScenarioEventDefinition,
    ScenarioEventEffect,
    ScenarioEventSignalDefinition,
    ScenarioEventTrigger,
)
from crisis_room.state.events import EventChoiceOption
from crisis_room.state.signals import PayloadType, SignalChannel, SignalVisibility


def cuban_scenario_events() -> list[ScenarioEventDefinition]:
    return [
        ScenarioEventDefinition(
            event_id="quarantine_contact_warning",
            title="Quarantine Contact Warning",
            summary=(
                "A Soviet-bloc vessel appears to be approaching the quarantine line "
                "faster than the naval picture can be reconciled."
            ),
            kind="historical_pressure",
            trigger=ScenarioEventTrigger(
                required_any_action_ids=["cuba_announce_naval_quarantine"],
                probability=1.0,
            ),
            effects=ScenarioEventEffect(
                truth_metric_effects={"escalation_pressure": 0.04},
                public_metric_effects={"public_alarm": 0.05, "market_anxiety": 0.04},
                clock_effects={
                    "quarantine_incident_risk": 0.07,
                    "nuclear_escalation": 0.04,
                },
            ),
            signals=[
                ScenarioEventSignalDefinition(
                    target_entity_ids=["us_excomm"],
                    channel=SignalChannel.MILITARY,
                    payload_type=PayloadType.MILITARY_MOVEMENT_OBSERVATION,
                    content=(
                        "Navy reports a contact nearing the quarantine line; identity "
                        "and orders are still being reconciled."
                    ),
                    visibility=SignalVisibility.COVERT,
                    reliability=0.76,
                    distortion_risk=0.16,
                    urgency=0.82,
                )
            ],
            visible_to=["us_excomm"],
            related_entity_ids=["soviet_presidium"],
            related_action_ids=["cuba_announce_naval_quarantine"],
            problem_title="Quarantine contact nearing the line",
            problem_summary=(
                "Naval contact reports are urgent but imperfect; a public order may "
                "now collide with local command decisions."
            ),
            urgency="high",
            choices=[
                ScenarioEventChoiceDefinition(
                    choice_id="quarantine_contact_response",
                    prompt="Decide how EXCOMM responds to the quarantine contact warning.",
                    options=[
                        EventChoiceOption(
                            option_id="deconflict",
                            label="Tighten military readiness",
                            summary=(
                                "Use disciplined readiness orders to slow local command "
                                "decisions around the quarantine line."
                            ),
                            action_id="military_posture",
                            capability_id="cuba_raise_defcon_readiness",
                            target_ids=["soviet_presidium"],
                            channel=SignalChannel.MILITARY,
                            consumes_normal_action_budget=True,
                        ),
                        EventChoiceOption(
                            option_id="private_probe",
                            label="Probe privately before public escalation",
                            summary=(
                                "Use the private Kremlin channel to clarify whether the "
                                "contact is intentional or local confusion."
                            ),
                            action_id="private_diplomacy",
                            capability_id="cuba_open_kremlin_channel",
                            target_ids=["soviet_presidium"],
                            channel=SignalChannel.BACKCHANNEL,
                            consumes_normal_action_budget=True,
                        ),
                    ],
                    visible_to=["us_excomm"],
                    expires_after_turns=1,
                )
            ],
        ),
        ScenarioEventDefinition(
            event_id="recon_air_defense_scare",
            title="Reconnaissance Air-Defense Scare",
            summary=(
                "Cuban and Soviet local air-defense reporting becomes noisy enough "
                "that an overflight could be misread as attack preparation."
            ),
            kind="local_initiative",
            trigger=ScenarioEventTrigger(
                required_any_action_ids=[
                    "cuba_recon_overflights",
                    "cuba_air_defense_alert",
                ],
                hidden_clock_minimums={"command_and_control_risk": 0.34},
                probability=1.0,
            ),
            effects=ScenarioEventEffect(
                truth_metric_effects={"escalation_pressure": 0.05},
                public_metric_effects={"public_alarm": 0.03},
                clock_effects={
                    "command_and_control_risk": 0.07,
                    "nuclear_escalation": 0.04,
                },
            ),
            signals=[
                ScenarioEventSignalDefinition(
                    target_entity_ids=["us_excomm"],
                    channel=SignalChannel.INTEL,
                    payload_type=PayloadType.INTEL_REPORT,
                    content=(
                        "Intercepts suggest confused local air-defense traffic around "
                        "reconnaissance routes."
                    ),
                    visibility=SignalVisibility.SECRET,
                    reliability=0.62,
                    distortion_risk=0.2,
                    urgency=0.76,
                )
            ],
            visible_to=["us_excomm"],
            related_entity_ids=["cuba", "soviet_presidium"],
            related_action_ids=["cuba_recon_overflights", "cuba_air_defense_alert"],
            problem_title="Local air defense picture is unstable",
            problem_summary=(
                "Reconnaissance is producing value, but local units may be closer to "
                "shooting or misreading orders than national leaders intend."
            ),
            urgency="high",
        ),
        ScenarioEventDefinition(
            event_id="allied_jupiter_anxiety",
            title="Allied Jupiter Anxiety",
            summary=(
                "An allied capital hears enough private movement around a possible "
                "missile bargain to worry that NATO could be surprised."
            ),
            kind="institutional_friction",
            trigger=ScenarioEventTrigger(
                required_any_action_ids=[
                    "cuba_secret_jupiter_trade",
                    "cuba_offer_non_invasion_pledge",
                ],
                probability=1.0,
            ),
            effects=ScenarioEventEffect(
                truth_metric_effects={"alliance_cohesion": -0.05},
                public_metric_effects={"allied_confidence": -0.08},
                clock_effects={"backchannel_viability": -0.04},
                relationship_effects={"us_excomm->nato_allies": {"trust": -0.08}},
            ),
            signals=[
                ScenarioEventSignalDefinition(
                    target_entity_ids=["us_excomm"],
                    channel=SignalChannel.PRIVATE_DIPLOMATIC,
                    payload_type=PayloadType.PRIVATE_DIPLOMATIC_MESSAGE,
                    content=(
                        "An allied government privately warns that any Turkey missile "
                        "understanding must not blindside NATO."
                    ),
                    visibility=SignalVisibility.PRIVATE,
                    reliability=0.82,
                    leak_risk=0.04,
                    distortion_risk=0.1,
                    urgency=0.58,
                )
            ],
            visible_to=["us_excomm"],
            related_entity_ids=["nato_allies"],
            related_action_ids=["cuba_secret_jupiter_trade", "cuba_offer_non_invasion_pledge"],
            problem_title="Allied confidence is strained",
            problem_summary=(
                "Private bargaining can help end the crisis, but allied governments "
                "may punish Washington if they learn the settlement late."
            ),
            urgency="medium",
        ),
        ScenarioEventDefinition(
            event_id="direct_backchannel_message_leak",
            title="Direct Backchannel Message Leak",
            summary=(
                "Rumors surface that Washington and Moscow exchanged a direct "
                "private message outside formal diplomatic channels."
            ),
            kind="media_leak",
            trigger=ScenarioEventTrigger(
                required_any_leaked_signal_capability_ids=[
                    "cuba_direct_kremlin_message"
                ],
                probability=1.0,
            ),
            effects=ScenarioEventEffect(
                public_metric_effects={"public_alarm": 0.04, "market_anxiety": 0.03},
                clock_effects={"backchannel_viability": -0.05},
            ),
            signals=[
                ScenarioEventSignalDefinition(
                    target_entity_ids=["us_excomm"],
                    channel=SignalChannel.MEDIA,
                    payload_type=PayloadType.RUMOR,
                    content=(
                        "Press chatter hints at a private U.S.-Soviet exchange, "
                        "with no confirmed text or public attribution."
                    ),
                    visibility=SignalVisibility.PUBLIC,
                    reliability=0.42,
                    distortion_risk=0.18,
                    urgency=0.55,
                    classification="rumor",
                )
            ],
            visible_to=["us_excomm"],
            related_entity_ids=["soviet_presidium"],
            related_action_ids=["cuba_direct_kremlin_message"],
            problem_title="Private message may be leaking",
            problem_summary=(
                "A direct backchannel can still move the crisis, but public rumor "
                "may force both sides to deny or harden their positions."
            ),
            urgency="medium",
            public_timeline_title="Backchannel Rumor Spreads",
            public_timeline_summary=(
                "Unconfirmed reports suggest private U.S.-Soviet contact."
            ),
        ),
        ScenarioEventDefinition(
            event_id="missile_sites_near_operational",
            title="Missile Sites Near Operational",
            summary=(
                "Intelligence estimates now warn that some missile sites may soon "
                "be ready enough to change EXCOMM's room for maneuver."
            ),
            kind="historical_pressure",
            trigger=ScenarioEventTrigger(
                truth_metric_minimums={"missile_operational_progress": 0.75},
                probability=1.0,
            ),
            effects=ScenarioEventEffect(
                truth_metric_effects={"hawk_pressure": 0.05, "verification_gap": 0.03},
                public_metric_effects={"public_alarm": 0.04},
                clock_effects={"invasion_momentum": 0.06, "nuclear_escalation": 0.03},
            ),
            signals=[
                ScenarioEventSignalDefinition(
                    target_entity_ids=["us_excomm"],
                    channel=SignalChannel.INTEL,
                    payload_type=PayloadType.INTEL_REPORT,
                    content=(
                        "Site readiness estimates are compressing; verification "
                        "is no longer a background task."
                    ),
                    visibility=SignalVisibility.SECRET,
                    reliability=0.72,
                    urgency=0.78,
                )
            ],
            visible_to=["us_excomm"],
            related_entity_ids=["cuba", "soviet_presidium"],
            problem_title="Missile readiness window is closing",
            problem_summary=(
                "The room may have less time than public posture suggests; "
                "verification and off-ramp pressure now compete directly."
            ),
            urgency="high",
        ),
        ScenarioEventDefinition(
            event_id="local_commander_acts",
            title="Local Commander Acts",
            summary=(
                "A local commander takes an aggressive readiness step before "
                "national leaders can fully coordinate the meaning of the order."
            ),
            kind="local_initiative",
            trigger=ScenarioEventTrigger(
                hidden_clock_minimums={"command_and_control_risk": 0.65},
                probability=1.0,
            ),
            effects=ScenarioEventEffect(
                truth_metric_effects={"escalation_pressure": 0.06},
                public_metric_effects={"public_alarm": 0.04},
                clock_effects={"nuclear_escalation": 0.07},
            ),
            signals=[
                ScenarioEventSignalDefinition(
                    target_entity_ids=["us_excomm"],
                    channel=SignalChannel.MILITARY,
                    payload_type=PayloadType.MILITARY_MOVEMENT_OBSERVATION,
                    content="Operational reporting shows a local unit moving ahead of political guidance.",
                    visibility=SignalVisibility.COVERT,
                    reliability=0.64,
                    urgency=0.84,
                )
            ],
            visible_to=["us_excomm"],
            related_entity_ids=["cuba", "soviet_presidium"],
            problem_title="Local command initiative is breaking containment",
            problem_summary=(
                "Command risk is now tangible: national leaders may be reacting "
                "to local initiative rather than controlling it."
            ),
            urgency="critical",
        ),
        ScenarioEventDefinition(
            event_id="backchannel_collapses",
            title="Backchannel Collapses",
            summary=(
                "Private-channel trust erodes far enough that deniable messages "
                "are now more likely to confuse or leak than settle the crisis."
            ),
            kind="institutional_friction",
            trigger=ScenarioEventTrigger(
                hidden_clock_maximums={"backchannel_viability": 0.3},
                probability=1.0,
            ),
            effects=ScenarioEventEffect(
                truth_metric_effects={"diplomatic_offramp": -0.08},
                public_metric_effects={"press_alarm": 0.03},
                clock_effects={"nuclear_escalation": 0.03},
            ),
            signals=[
                ScenarioEventSignalDefinition(
                    target_entity_ids=["us_excomm"],
                    channel=SignalChannel.PRIVATE_DIPLOMATIC,
                    payload_type=PayloadType.PRIVATE_DIPLOMATIC_MESSAGE,
                    content="Private envoys report that deniable messages are losing credibility.",
                    visibility=SignalVisibility.PRIVATE,
                    reliability=0.78,
                    urgency=0.72,
                )
            ],
            visible_to=["us_excomm"],
            related_entity_ids=["soviet_presidium"],
            problem_title="Backchannel is no longer reliable",
            problem_summary=(
                "Private diplomacy may still matter, but the channel now carries "
                "more leak and misread risk than leverage."
            ),
            urgency="high",
        ),
        ScenarioEventDefinition(
            event_id="congressional_revolt",
            title="Congressional Revolt",
            summary=(
                "Lawmakers demand clarity as private reports suggest the White "
                "House may be trading too much restraint for too little verification."
            ),
            kind="media_leak",
            trigger=ScenarioEventTrigger(
                truth_metric_maximums={"domestic_trust": 0.25},
                probability=1.0,
            ),
            effects=ScenarioEventEffect(
                truth_metric_effects={"domestic_trust": -0.08, "hawk_pressure": 0.06},
                public_metric_effects={"press_alarm": 0.05},
            ),
            signals=[
                ScenarioEventSignalDefinition(
                    target_entity_ids=["us_excomm"],
                    channel=SignalChannel.MEDIA,
                    payload_type=PayloadType.MEDIA_REPORT,
                    content="Congressional voices demand a harder public line on Cuba.",
                    visibility=SignalVisibility.PUBLIC,
                    reliability=0.82,
                    urgency=0.7,
                    classification="public",
                )
            ],
            visible_to=["us_excomm"],
            related_entity_ids=["us_excomm"],
            problem_title="Domestic coalition is splitting",
            problem_summary=(
                "Domestic pressure has become an active crisis constraint rather "
                "than background noise."
            ),
            urgency="high",
            public_timeline_title="Congress Splits Over Cuba Line",
            public_timeline_summary=(
                "Lawmakers demand clarity as reports suggest private concessions "
                "may be under discussion."
            ),
        ),
        ScenarioEventDefinition(
            event_id="security_chiefs_demand_hard_line",
            title="Security Chiefs Demand Hard Line",
            summary=(
                "Security leaders begin treating compromise as a loss of control "
                "unless it is paired with visible verification or force."
            ),
            kind="institutional_friction",
            trigger=ScenarioEventTrigger(
                truth_metric_minimums={
                    "hawk_pressure": 0.75,
                    "perceived_weakness": 0.65,
                },
                public_metric_minimums={"public_confidence": 0.55},
                probability=1.0,
            ),
            effects=ScenarioEventEffect(
                truth_metric_effects={"institutional_loyalty": -0.08},
                clock_effects={"invasion_momentum": 0.08},
            ),
            signals=[
                ScenarioEventSignalDefinition(
                    target_entity_ids=["us_excomm"],
                    channel=SignalChannel.MILITARY,
                    payload_type=PayloadType.GAMEMASTER_RULING,
                    content="Senior security voices are aligning around a harder line.",
                    visibility=SignalVisibility.PRIVATE,
                    reliability=0.86,
                    urgency=0.78,
                )
            ],
            visible_to=["us_excomm"],
            related_entity_ids=["us_excomm"],
            problem_title="Security chiefs are hardening",
            problem_summary=(
                "Hawk pressure and perceived weakness now threaten presidential "
                "control inside the room."
            ),
            urgency="high",
        ),
    ]
