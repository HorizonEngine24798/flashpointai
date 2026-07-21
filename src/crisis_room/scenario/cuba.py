from __future__ import annotations

from crisis_room.scenario.cuba_advisors import initial_us_excomm_advisor_council
from crisis_room.scenario.cuba_capabilities import cuban_scenario_capabilities
from crisis_room.scenario.cuba_endings import cuban_scenario_endings
from crisis_room.scenario.cuba_events import cuban_scenario_events
from crisis_room.scenario.cuba_pressure import (
    cuban_hidden_obligations,
    cuban_pressure_rules,
)
from crisis_room.scenario.events import ScenarioEventSettings
from crisis_room.scenario.generic_actions import generic_action_catalog
from crisis_room.scenario.schema import Scenario, ScenarioEntitySpec, ScenarioMetadata
from crisis_room.state.beliefs import BeliefClaim, BeliefState, InternalNarrative
from crisis_room.state.timelines import TimelineEntry, TimelineScope
from crisis_room.state.world import EntityType


CUBA_OPEN_KREMLIN_CHANNEL_CAPABILITY_ID = "cuba_open_kremlin_channel"
CUBA_DIRECT_KREMLIN_MESSAGE_CAPABILITY_ID = "cuba_direct_kremlin_message"
CUBA_PUBLIC_WITHDRAWAL_DEMAND_CAPABILITY_ID = "cuba_public_withdrawal_demand"
CUBA_ANNOUNCE_NAVAL_QUARANTINE_CAPABILITY_ID = "cuba_announce_naval_quarantine"
CUBA_RECON_OVERFLIGHTS_CAPABILITY_ID = "cuba_recon_overflights"
CUBA_RAISE_DEFCON_READINESS_CAPABILITY_ID = "cuba_raise_defcon_readiness"
CUBA_OFFER_NON_INVASION_PLEDGE_CAPABILITY_ID = "cuba_offer_non_invasion_pledge"
CUBA_SECRET_JUPITER_TRADE_CAPABILITY_ID = "cuba_secret_jupiter_trade"
CUBA_PREPARE_AIR_STRIKE_CAPABILITY_ID = "cuba_prepare_air_strike"
CUBA_AIR_DEFENSE_ALERT_CAPABILITY_ID = "cuba_air_defense_alert"

CUBA_PRIVATE_EXIT_CAPABILITY_IDS = {
    CUBA_OPEN_KREMLIN_CHANNEL_CAPABILITY_ID,
    CUBA_OFFER_NON_INVASION_PLEDGE_CAPABILITY_ID,
    CUBA_SECRET_JUPITER_TRADE_CAPABILITY_ID,
}
CUBA_CREDIBLE_PRESSURE_CAPABILITY_IDS = {
    CUBA_ANNOUNCE_NAVAL_QUARANTINE_CAPABILITY_ID,
    CUBA_RAISE_DEFCON_READINESS_CAPABILITY_ID,
    CUBA_PREPARE_AIR_STRIKE_CAPABILITY_ID,
}
CUBA_PUBLIC_LINE_CAPABILITY_IDS = {
    CUBA_PUBLIC_WITHDRAWAL_DEMAND_CAPABILITY_ID,
    CUBA_ANNOUNCE_NAVAL_QUARANTINE_CAPABILITY_ID,
}


def build_cuban_missile_crisis_1962_scenario() -> Scenario:
    return Scenario(
        scenario_id="cuban_missile_crisis_1962",
        metadata=ScenarioMetadata(
            title="Cuban Missile Crisis 1962",
            historical_period="October 1962",
            description=(
                "A simplified crisis room vertical slice centered on U.S. EXCOMM "
                "after U-2 photography confirms Soviet missile sites in Cuba."
            ),
            designer_notes=[
                "Historical gravity: U-2 imagery has confirmed Soviet MRBM/IRBM sites in Cuba.",
                "The player is U.S. EXCOMM. Publicly, the crisis is still partly obscured.",
                "Core pressure: quarantine versus air strike or invasion, with diplomacy trying to preserve a face-saving exit.",
                "Backchannel gravity: a non-invasion pledge and a secret Jupiter missile understanding can unlock de-escalation.",
                "Chaos pressure: reconnaissance incidents, local Cuban air defense initiative, confused naval contact, leaks, and alliance anxiety.",
                "Keep history as gravity, not rails: the crisis can stabilize, spiral, or settle through different public-private packages.",
            ],
        ),
        intro_text=(
            "October 1962. U-2 photography has reached Washington: Soviet nuclear "
            "missile sites are under construction in Cuba. The public does not yet "
            "know the full story. Inside EXCOMM, advisors are split between a strike, "
            "a naval quarantine, and a private bargain that might remove the missiles "
            "without forcing Moscow into public humiliation."
        ),
        player_entity_id="us_excomm",
        entities=[
            ScenarioEntitySpec(
                entity_id="us_excomm",
                name="U.S. EXCOMM",
                entity_type=EntityType.PLAYER_FACTION,
                role="Player-controlled White House crisis committee advising President Kennedy",
                public_goals=[
                    "Remove Soviet offensive missiles from Cuba",
                    "Avoid a nuclear exchange",
                    "Maintain U.S. credibility with allies and domestic audiences",
                ],
                private_goals=[
                    "Preserve presidential control over escalation",
                    "Find a face-saving Soviet off-ramp",
                    "Avoid revealing any secret Jupiter missile trade publicly",
                ],
                resources={
                    "political_capital": 7,
                    "military_readiness": 5,
                    "intelligence_focus": 4,
                    "alliance_credit": 3,
                },
                initial_beliefs=BeliefState(
                    summary=(
                        "EXCOMM has high-confidence U-2 evidence of Soviet missile "
                        "sites in Cuba, but uncertain Soviet intent and Cuban command discipline."
                    ),
                    claims={
                        "missile_sites": BeliefClaim(
                            topic="missile_sites",
                            summary="U-2 photography shows MRBM/IRBM sites under construction in Cuba.",
                            confidence=0.92,
                        ),
                        "soviet_intent": BeliefClaim(
                            topic="soviet_intent",
                            summary=(
                                "Khrushchev may be deterring invasion, altering the strategic balance, "
                                "or trading pressure for concessions elsewhere."
                            ),
                            confidence=0.55,
                        ),
                        "offramp": BeliefClaim(
                            topic="offramp",
                            summary=(
                                "A non-invasion pledge and private discussion of obsolete Jupiter "
                                "missiles may be enough for Moscow to withdraw."
                            ),
                            confidence=0.48,
                        ),
                    },
                    uncertainty_notes=[
                        "Whether missiles are operational is not fully settled.",
                        "Cuban or Soviet local commanders may react faster than leaders can control.",
                    ],
                ),
                internal_narratives=[
                    InternalNarrative(
                        narrative_id="hawk",
                        name="Air Strike Bloc",
                        worldview="Missiles in Cuba are intolerable and delay lets them become operational.",
                        preferred_strategy="Prepare air strikes and invasion while making public resolve unmistakable.",
                        fear="A quarantine buys time for Moscow and Havana.",
                        red_lines=["Operational nuclear missiles in Cuba", "Soviet refusal to halt work"],
                        influence_weight=0.46,
                    ),
                    InternalNarrative(
                        narrative_id="restraint",
                        name="Controlled Quarantine Bloc",
                        worldview="A public quarantine plus private bargaining can apply pressure without starting war.",
                        preferred_strategy="Use quarantine, OAS/UN legitimacy, and backchannels before irreversible attack.",
                        fear="An air strike kills Soviet personnel and hands escalation to local commanders.",
                        red_lines=["Loss of presidential control", "No diplomatic channel remaining"],
                        influence_weight=0.54,
                    ),
                    InternalNarrative(
                        narrative_id="bargain",
                        name="Private Bargain Bloc",
                        worldview="Khrushchev needs a public retreat to look survivable at home and in the bloc.",
                        preferred_strategy="Offer a non-invasion pledge and a deniable Jupiter missile understanding.",
                        fear="Public victory rhetoric destroys the only face-saving exit.",
                        red_lines=["Public admission of a Turkey missile trade"],
                        influence_weight=0.35,
                    ),
                ],
            ),
            ScenarioEntitySpec(
                entity_id="soviet_presidium",
                name="Soviet Presidium",
                entity_type=EntityType.OPPOSING_FACTION,
                role="Kremlin leadership around Nikita Khrushchev",
                public_goals=[
                    "Defend Cuba from invasion",
                    "Avoid appearing to capitulate to U.S. pressure",
                ],
                private_goals=[
                    "Secure a U.S. non-invasion pledge",
                    "Extract a quiet concession on Jupiter missiles in Turkey",
                    "Avoid a direct U.S.-Soviet war",
                ],
                resources={
                    "political_capital": 5,
                    "military_readiness": 4,
                    "diplomatic_flexibility": 3,
                },
                initial_beliefs=BeliefState(
                    summary=(
                        "Moscow believes Cuba needs protection and that Washington may "
                        "prefer pressure to invasion, but U.S. domestic politics are uncertain."
                    ),
                    claims={
                        "us_posture": BeliefClaim(
                            topic="us_posture",
                            summary="U.S. leadership is alarmed but may still accept a private bargain.",
                            confidence=0.55,
                        ),
                        "cuba_security": BeliefClaim(
                            topic="cuba_security",
                            summary="Castro expects invasion and may press for harder Soviet guarantees.",
                            confidence=0.7,
                        ),
                    },
                    uncertainty_notes=[
                        "The exact U.S. threshold for an air strike is unclear.",
                        "Public pressure may force Washington away from a bargain.",
                    ],
                ),
                internal_narratives=[
                    InternalNarrative(
                        narrative_id="hold_line",
                        name="Prestige Faction",
                        worldview="Backing down under quarantine would damage Soviet credibility worldwide.",
                        preferred_strategy="Deny offensive intent, keep ships moving, demand reciprocal concessions.",
                        fear="A retreat without compensation encourages future U.S. coercion.",
                        red_lines=["Public humiliation", "Unconditional withdrawal"],
                        influence_weight=0.52,
                    ),
                    InternalNarrative(
                        narrative_id="settlement",
                        name="Settlement Faction",
                        worldview="A survivable compromise protects Cuba and avoids nuclear war.",
                        preferred_strategy="Trade missiles for non-invasion and a quiet Jupiter understanding.",
                        fear="Local military incidents lock both leaders into escalation.",
                        red_lines=["U.S. attack on Cuba", "No guarantee for Cuba"],
                        influence_weight=0.48,
                    ),
                ],
            ),
            ScenarioEntitySpec(
                entity_id="cuba",
                name="Cuban Revolutionary Government",
                entity_type=EntityType.OPPOSING_FACTION,
                role="Fidel Castro's government and Cuban military command",
                public_goals=[
                    "Deter another U.S. invasion",
                    "Defend Cuban sovereignty",
                ],
                private_goals=[
                    "Keep Soviet protection credible",
                    "Avoid being traded away without Cuban consent",
                ],
                resources={
                    "political_capital": 4,
                    "military_readiness": 4,
                    "air_defense_control": 3,
                },
                initial_beliefs=BeliefState(
                    summary=(
                        "Havana expects invasion planning and sees U.S. reconnaissance "
                        "as preparation for attack."
                    ),
                    claims={
                        "invasion_threat": BeliefClaim(
                            topic="invasion_threat",
                            summary="The United States may use the missile issue to justify invasion.",
                            confidence=0.76,
                        )
                    },
                    uncertainty_notes=[
                        "Moscow's willingness to defend Cuba under direct U.S. pressure is uncertain."
                    ],
                ),
                internal_narratives=[
                    InternalNarrative(
                        narrative_id="defiant",
                        name="Defiant Defense Bloc",
                        worldview="Only visible readiness deters invasion.",
                        preferred_strategy="Raise air defense posture and reject humiliating inspections.",
                        fear="Cuba becomes a bargaining chip between superpowers.",
                        red_lines=["U.S. invasion", "Forced inspections"],
                        influence_weight=0.65,
                    ),
                    InternalNarrative(
                        narrative_id="survival",
                        name="Regime Survival Bloc",
                        worldview="Survival requires Soviet support but not uncontrolled nuclear war.",
                        preferred_strategy="Press Moscow privately while avoiding actions that invite air strikes.",
                        fear="Local escalation gives Washington a pretext.",
                        red_lines=["Loss of Soviet protection"],
                        influence_weight=0.35,
                    ),
                ],
            ),
            ScenarioEntitySpec(
                entity_id="nato_allies",
                name="NATO Allies",
                entity_type=EntityType.ALLIED_FACTION,
                role="Key allied governments balancing support for Washington with fear of nuclear escalation",
                public_goals=[
                    "Preserve alliance unity",
                    "Avoid nuclear war in Europe",
                ],
                private_goals=[
                    "Understand whether Turkey-based Jupiter missiles are in play",
                    "Keep Washington from blindsiding allies",
                ],
                resources={
                    "political_capital": 3,
                    "alliance_credit": 4,
                    "diplomatic_flexibility": 2,
                },
                initial_beliefs=BeliefState(
                    summary=(
                        "Allied governments support consultation but worry the crisis "
                        "could spread to Europe or expose alliance missile politics."
                    ),
                    claims={
                        "alliance_risk": BeliefClaim(
                            topic="alliance_risk",
                            summary="A public missile trade involving Turkey could damage NATO cohesion.",
                            confidence=0.72,
                        )
                    },
                    uncertainty_notes=[
                        "The extent of U.S. willingness to bargain over Jupiter missiles is unclear."
                    ],
                ),
                internal_narratives=[
                    InternalNarrative(
                        narrative_id="solidarity",
                        name="Solidarity Bloc",
                        worldview="The alliance must back Washington against Soviet coercion.",
                        preferred_strategy="Support public pressure while asking for disciplined consultation.",
                        fear="Visible allied hesitation fractures deterrence.",
                        influence_weight=0.55,
                    ),
                    InternalNarrative(
                        narrative_id="european_risk",
                        name="European Risk Bloc",
                        worldview="The crisis could spill into Berlin, Turkey, and European nuclear politics.",
                        preferred_strategy="Push privately for de-escalation and avoid a public Jupiter trade.",
                        fear="Europe pays the price for a Caribbean showdown.",
                        influence_weight=0.45,
                    ),
                ],
            ),
            ScenarioEntitySpec(
                entity_id="international",
                name="International Community",
                entity_type=EntityType.INTERNATIONAL_COMMUNITY,
                role="UN, OAS, non-aligned governments, media, markets, and legitimacy pressure",
                public_goals=[
                    "Prevent nuclear war",
                    "Create space for inspected withdrawal and restraint",
                ],
                private_goals=[
                    "Keep both superpowers communicating",
                    "Reduce panic without hiding the danger",
                ],
            ),
        ],
        initial_public_timeline=[
            TimelineEntry(
                turn=0,
                scope=TimelineScope.PUBLIC,
                title="Rumors Around Cuba Intensify",
                summary=(
                    "Foreign ministries and newspapers report unusual tension around Cuba, "
                    "but Washington has not yet disclosed the missile photographs."
                ),
                source="scenario_seed",
                tags=["seed", "public"],
            )
        ],
        initial_omniscient_timeline=[
            TimelineEntry(
                turn=0,
                scope=TimelineScope.OMNISCIENT,
                title="U-2 Photographs Confirm Missile Sites",
                summary=(
                    "High-altitude reconnaissance has identified Soviet medium- and "
                    "intermediate-range missile sites under construction in Cuba."
                ),
                source="scenario_seed",
                tags=["seed", "classified", "u2"],
            )
        ],
        initial_entity_timelines={
            "us_excomm": [
                TimelineEntry(
                    turn=0,
                    scope=TimelineScope.ENTITY_LOCAL,
                    title="Classified Briefing",
                    summary=(
                        "CIA imagery analysts brief EXCOMM that Soviet missile sites "
                        "are under construction near San Cristobal and other Cuban locations."
                    ),
                    visible_to=["us_excomm"],
                    source="scenario_seed",
                    tags=["classified", "u2", "excomm"],
                )
            ],
            "soviet_presidium": [
                TimelineEntry(
                    turn=0,
                    scope=TimelineScope.ENTITY_LOCAL,
                    title="Deployment Nears Exposure",
                    summary=(
                        "Moscow expects U.S. surveillance to discover the Cuban deployment "
                        "before all sites are fully ready."
                    ),
                    visible_to=["soviet_presidium"],
                    source="scenario_seed",
                    tags=["classified", "kremlin"],
                )
            ],
            "cuba": [
                TimelineEntry(
                    turn=0,
                    scope=TimelineScope.ENTITY_LOCAL,
                    title="Invasion Fear Hardens",
                    summary=(
                        "Havana sees U.S. reconnaissance and regional pressure as signs "
                        "that invasion planning may be accelerating."
                    ),
                    visible_to=["cuba"],
                    source="scenario_seed",
                    tags=["local", "defense"],
                )
            ],
            "nato_allies": [
                TimelineEntry(
                    turn=0,
                    scope=TimelineScope.ENTITY_LOCAL,
                    title="Urgent Allied Consultations",
                    summary=(
                        "Allied capitals receive indications that Washington is preparing "
                        "a major Cuba announcement and may ask for public support."
                    ),
                    visible_to=["nato_allies"],
                    source="scenario_seed",
                    tags=["alliance", "consultation"],
                )
            ],
        },
        initial_truth_metrics={
            "escalation_pressure": 0.42,
            "missile_operational_progress": 0.58,
            "diplomatic_offramp": 0.46,
            "alliance_cohesion": 0.62,
            "soviet_face_saving_need": 0.78,
            "cuban_invasion_fear": 0.82,
            "domestic_trust": 0.62,
            "hawk_pressure": 0.48,
            "perceived_weakness": 0.34,
            "institutional_loyalty": 0.7,
            "verification_gap": 0.36,
            "leak_pressure": 0.24,
        },
        initial_public_metrics={
            "public_alarm": 0.28,
            "public_confidence": 0.55,
            "press_alarm": 0.22,
            "market_anxiety": 0.34,
            "allied_confidence": 0.55,
        },
        initial_hidden_clocks={
            "nuclear_escalation": 0.34,
            "invasion_momentum": 0.38,
            "command_and_control_risk": 0.27,
            "quarantine_incident_risk": 0.2,
            "backchannel_viability": 0.56,
        },
        initial_advisor_councils={
            "us_excomm": initial_us_excomm_advisor_council(),
        },
        scenario_events=cuban_scenario_events(),
        scenario_endings=cuban_scenario_endings(),
        pressure_rules=cuban_pressure_rules(),
        hidden_obligations=cuban_hidden_obligations(),
        event_settings=ScenarioEventSettings(
            base_max_events_per_turn=1,
            high_pressure_max_events_per_turn=2,
            action_density_bonus_threshold=3,
            escalation_pressure_threshold=0.62,
            allow_llm_event_candidates=True,
            llm_candidate_min_plausibility=0.62,
            llm_candidate_min_escalation_pressure=0.58,
            llm_candidate_effect_clamp=0.03,
        ),
        action_catalog=generic_action_catalog(),
        capabilities=cuban_scenario_capabilities(),
    )
