from __future__ import annotations

from crisis_room.scenario.events import ScenarioEventEffect
from crisis_room.scenario.pressure import HiddenObligation, PressureRule
from crisis_room.state.signals import SignalChannel


def cuban_pressure_rules() -> list[PressureRule]:
    return [
        PressureRule(
            rule_id="excomm_formal_action_tax",
            title="Formal Action Tax",
            applies_to_actor_ids=["us_excomm"],
            effects=ScenarioEventEffect(
                clock_effects={
                    "nuclear_escalation": 0.01,
                    "command_and_control_risk": 0.01,
                }
            ),
            reason="Every formal EXCOMM move adds coordination strain.",
        ),
        PressureRule(
            rule_id="excomm_military_action_tax",
            title="Military Pressure Tax",
            applies_to_actor_ids=["us_excomm"],
            applies_to_categories=["military"],
            effects=ScenarioEventEffect(
                truth_metric_effects={
                    "hawk_pressure": -0.02,
                    "perceived_weakness": -0.03,
                },
                public_metric_effects={"public_alarm": 0.03},
                clock_effects={"nuclear_escalation": 0.04},
            ),
            reason="Force reassures hawks while raising public and accident risk.",
        ),
        PressureRule(
            rule_id="excomm_private_diplomacy_tax",
            title="Private Diplomacy Tax",
            applies_to_actor_ids=["us_excomm"],
            applies_to_categories=["diplomatic"],
            applies_to_channels=[
                SignalChannel.PRIVATE_DIPLOMATIC,
                SignalChannel.BACKCHANNEL,
            ],
            effects=ScenarioEventEffect(
                truth_metric_effects={
                    "domestic_trust": -0.01,
                    "leak_pressure": 0.03,
                    "perceived_weakness": 0.02,
                }
            ),
            reason="Quiet bargaining creates real political risk if it leaks.",
        ),
        PressureRule(
            rule_id="excomm_public_action_tax",
            title="Public Action Tax",
            applies_to_actor_ids=["us_excomm"],
            applies_to_channels=[SignalChannel.PUBLIC],
            effects=ScenarioEventEffect(
                truth_metric_effects={"hawk_pressure": -0.01},
                public_metric_effects={"public_alarm": 0.03, "press_alarm": 0.02},
                clock_effects={"backchannel_viability": -0.01},
            ),
            reason="Public resolve buys room with hawks while narrowing private flexibility.",
        ),
        PressureRule(
            rule_id="non_invasion_pledge_domestic_tax",
            title="Non-Invasion Pledge Domestic Tax",
            applies_to_capability_ids=["cuba_offer_non_invasion_pledge"],
            effects=ScenarioEventEffect(
                truth_metric_effects={
                    "domestic_trust": -0.04,
                    "hawk_pressure": 0.05,
                    "perceived_weakness": 0.05,
                    "verification_gap": 0.04,
                    "alliance_cohesion": -0.03,
                }
            ),
            reason="The pledge can be wise abroad and still read as a concession at home.",
        ),
        PressureRule(
            rule_id="secret_jupiter_trade_domestic_tax",
            title="Secret Jupiter Trade Domestic Tax",
            applies_to_capability_ids=["cuba_secret_jupiter_trade"],
            effects=ScenarioEventEffect(
                truth_metric_effects={
                    "domestic_trust": -0.05,
                    "leak_pressure": 0.08,
                    "perceived_weakness": 0.05,
                    "alliance_cohesion": -0.06,
                },
                public_metric_effects={"press_alarm": 0.03},
            ),
            reason="A secret missile trade is strategically useful and politically explosive.",
        ),
        PressureRule(
            rule_id="settlement_framework_offered",
            title="Settlement Framework Offered",
            applies_to_actor_ids=["us_excomm"],
            applies_to_capability_ids=[
                "cuba_offer_non_invasion_pledge",
                "cuba_secret_jupiter_trade",
            ],
            once_per_turn=True,
            effects=ScenarioEventEffect(
                active_commitments_added=["settlement_framework_offered"]
            ),
            reason="The player has put a concrete reciprocal settlement term on the table.",
        ),
    ]


def cuban_hidden_obligations() -> list[HiddenObligation]:
    return [
        HiddenObligation(
            obligation_id="missile_progress_control",
            title="Missile Progress Control",
            covered_by_capability_ids=[
                "cuba_recon_overflights",
                "cuba_offer_non_invasion_pledge",
                "cuba_secret_jupiter_trade",
            ],
            missed_effects=ScenarioEventEffect(
                truth_metric_effects={
                    "missile_operational_progress": 0.04,
                    "verification_gap": 0.03,
                },
                public_metric_effects={"public_alarm": 0.01},
            ),
            reason="The missile timeline advances when nobody verifies or constrains it.",
            visible_to_player=True,
            visible_summary=(
                "Missile readiness gains time while verification or bargaining lags."
            ),
        ),
        HiddenObligation(
            obligation_id="command_deconfliction",
            title="Command Deconfliction",
            covered_by_capability_ids=[
                "cuba_open_kremlin_channel",
                "cuba_direct_kremlin_message",
                "cuba_offer_non_invasion_pledge",
                "cuba_secret_jupiter_trade",
            ],
            missed_effects=ScenarioEventEffect(
                clock_effects={
                    "command_and_control_risk": 0.05,
                    "nuclear_escalation": 0.02,
                }
            ),
            reason="Local commanders become more dangerous when control lines decay.",
            visible_to_player=True,
            visible_summary="Local command risk rises when control lines are not tended.",
        ),
        HiddenObligation(
            obligation_id="domestic_management",
            title="Domestic Management",
            covered_by_capability_ids=[
                "cuba_public_withdrawal_demand",
                "cuba_announce_naval_quarantine",
                "cuba_brief_trusted_media",
                "cuba_monitor_public_mood",
                "cuba_rally_institutional_allies",
                "nato_reassurance_pressure",
            ],
            missed_effects=ScenarioEventEffect(
                truth_metric_effects={
                    "domestic_trust": -0.04,
                    "hawk_pressure": 0.03,
                },
                public_metric_effects={"press_alarm": 0.03},
            ),
            reason="Political actors fill silence with their own interpretation.",
            visible_to_player=True,
            visible_summary="Domestic hawks and press interpretation fill the silence.",
        ),
        HiddenObligation(
            obligation_id="alliance_management",
            title="Alliance Management",
            covered_by_capability_ids=[
                "nato_reassurance_pressure",
                "cuba_rally_institutional_allies",
                "cuba_secret_jupiter_trade",
            ],
            missed_effects=ScenarioEventEffect(
                truth_metric_effects={"alliance_cohesion": -0.03},
                public_metric_effects={"allied_confidence": -0.03},
            ),
            reason="Allies punish strategic surprises even when the main crisis is elsewhere.",
            visible_to_player=True,
            visible_summary="Allied confidence frays when consultation lags.",
        ),
        HiddenObligation(
            obligation_id="backchannel_maintenance",
            title="Backchannel Maintenance",
            covered_by_capability_ids=[
                "cuba_open_kremlin_channel",
                "cuba_direct_kremlin_message",
                "cuba_offer_non_invasion_pledge",
                "cuba_secret_jupiter_trade",
                "soviet_compromise_probe",
            ],
            missed_effects=ScenarioEventEffect(
                clock_effects={"backchannel_viability": -0.04}
            ),
            reason="Private-channel credibility fades if nobody tends it.",
            visible_to_player=True,
            visible_summary="Private-channel credibility fades without fresh contact.",
        ),
    ]
