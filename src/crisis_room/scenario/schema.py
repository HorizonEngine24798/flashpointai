from __future__ import annotations

from pydantic import BaseModel, Field

from crisis_room.engine.actions import ActionCategory, ActionDefinition
from crisis_room.scenario.events import (
    ScenarioEventDefinition,
    ScenarioEventEffect,
    ScenarioEventSignalDefinition,
    ScenarioEventTrigger,
)
from crisis_room.state.advisors import AdvisorBelief, AdvisorCouncilState, AdvisorState
from crisis_room.state.beliefs import BeliefClaim, BeliefState, InternalNarrative
from crisis_room.state.signals import PayloadType, SignalChannel, SignalVisibility
from crisis_room.state.timelines import TimelineEntry, TimelineScope
from crisis_room.state.world import EntityState, EntityType, WorldStateV2


class ScenarioMetadata(BaseModel):
    title: str
    historical_period: str = ""
    description: str = ""
    designer_notes: list[str] = Field(default_factory=list)


class ScenarioEntitySpec(BaseModel):
    entity_id: str
    name: str
    entity_type: EntityType
    role: str
    public_goals: list[str] = Field(default_factory=list)
    private_goals: list[str] = Field(default_factory=list)
    internal_narratives: list[InternalNarrative] = Field(default_factory=list)
    initial_beliefs: BeliefState = Field(default_factory=BeliefState)
    resources: dict[str, int] = Field(default_factory=dict)
    doctrine: str = ""

    def to_entity_state(self) -> EntityState:
        return EntityState(
            entity_id=self.entity_id,
            name=self.name,
            entity_type=self.entity_type,
            role=self.role,
            public_goals=self.public_goals,
            private_goals=self.private_goals,
            internal_narratives=self.internal_narratives,
            beliefs=self.initial_beliefs,
            resources=self.resources,
            doctrine=self.doctrine,
        )


class Scenario(BaseModel):
    scenario_id: str
    metadata: ScenarioMetadata
    intro_text: str
    player_entity_id: str
    entities: list[ScenarioEntitySpec]
    action_catalog: list[ActionDefinition] = Field(default_factory=list)
    scenario_events: list[ScenarioEventDefinition] = Field(default_factory=list)
    initial_public_timeline: list[TimelineEntry] = Field(default_factory=list)
    initial_omniscient_timeline: list[TimelineEntry] = Field(default_factory=list)
    initial_entity_timelines: dict[str, list[TimelineEntry]] = Field(default_factory=dict)
    initial_truth_metrics: dict[str, float] = Field(default_factory=dict)
    initial_public_metrics: dict[str, float] = Field(default_factory=dict)
    initial_hidden_clocks: dict[str, float] = Field(default_factory=dict)
    initial_advisor_councils: dict[str, AdvisorCouncilState] = Field(default_factory=dict)
    channel_rules: dict[str, str | int | float | bool] = Field(default_factory=dict)

    def create_initial_world(self, rng_seed: int = 0) -> WorldStateV2:
        world = WorldStateV2(
            scenario_id=self.scenario_id,
            rng_seed=rng_seed,
            truth_metrics=self.initial_truth_metrics,
            public_metrics=self.initial_public_metrics,
            hidden_clocks=self.initial_hidden_clocks,
            advisor_councils={
                entity_id: council.model_copy(deep=True)
                for entity_id, council in self.initial_advisor_councils.items()
            },
            actors={entity.entity_id: entity.to_entity_state() for entity in self.entities},
            metadata={"player_entity_id": self.player_entity_id},
        )
        for entry in self.initial_public_timeline:
            world.public_timeline.append(entry)
        for entry in self.initial_omniscient_timeline:
            world.omniscient_timeline.append(entry)
        for entity in self.entities:
            timeline = world.ensure_entity_timeline(entity.entity_id)
            for entry in self.initial_entity_timelines.get(entity.entity_id, []):
                timeline.append(entry)
        return world


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
        },
        initial_public_metrics={
            "public_alarm": 0.28,
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
            "us_excomm": _initial_us_excomm_advisor_council(),
        },
        scenario_events=_cuban_scenario_events(),
        action_catalog=[
            ActionDefinition(
                action_id="private_kremlin_backchannel",
                title="Open Private Kremlin Backchannel",
                category=ActionCategory.DIPLOMATIC,
                actor_types_allowed=[
                    "player_faction",
                    "opposing_faction",
                    "allied_faction",
                ],
                targets_allowed=["player_faction", "opposing_faction", "allied_faction"],
                channels_allowed=[
                    SignalChannel.BACKCHANNEL,
                    SignalChannel.PRIVATE_DIPLOMATIC,
                ],
                required_resources={"political_capital": 1},
                resource_costs={"political_capital": 1},
                min_targets=1,
                max_targets=1,
                truth_metric_effects={
                    "escalation_pressure": -0.04,
                    "diplomatic_offramp": 0.08,
                },
                clock_effects={
                    "backchannel_viability": 0.08,
                    "nuclear_escalation": -0.03,
                },
                relationship_effects={"trust": 0.1},
                deescalation_potential=0.35,
                information_outputs=[PayloadType.BACKCHANNEL_MESSAGE],
                signal_reliability=0.85,
                signal_leak_risk=0.08,
                signal_distortion_risk=0.12,
                prompt_hints=[
                    "Use for Robert Kennedy/Dobrynin-style private probes.",
                    "Best when the intent is reciprocal restraint, face-saving, or testing a deal.",
                ],
            ),
            ActionDefinition(
                action_id="public_demand_withdrawal",
                title="Publicly Demand Missile Withdrawal",
                category=ActionCategory.INFORMATION,
                actor_types_allowed=["player_faction", "opposing_faction"],
                targets_allowed=["player_faction", "opposing_faction"],
                channels_allowed=[SignalChannel.PUBLIC],
                required_resources={"political_capital": 1},
                resource_costs={"political_capital": 1},
                min_targets=1,
                max_targets=2,
                public_metric_effects={"public_alarm": 0.14, "market_anxiety": 0.08},
                truth_metric_effects={"escalation_pressure": 0.06},
                clock_effects={"nuclear_escalation": 0.04, "backchannel_viability": -0.03},
                relationship_effects={"trust": -0.12},
                escalation_risk=0.3,
                information_outputs=[PayloadType.PUBLIC_STATEMENT],
                public_timeline_title="U.S. Public Demand",
                prompt_hints=[
                    "Use for Kennedy-style public warning, televised address, or demand for removal.",
                    "Raises public clarity and public risk at the same time.",
                ],
            ),
            ActionDefinition(
                action_id="announce_quarantine",
                title="Announce Naval Quarantine",
                category=ActionCategory.MILITARY,
                actor_types_allowed=["player_faction"],
                targets_allowed=["opposing_faction"],
                channels_allowed=[SignalChannel.PUBLIC, SignalChannel.MILITARY],
                required_resources={
                    "military_readiness": 2,
                    "political_capital": 1,
                    "alliance_credit": 1,
                },
                resource_costs={"political_capital": 1, "alliance_credit": 1},
                actor_resource_effects={"military_readiness": -1},
                preparation_turns=1,
                execution_turns=1,
                cooldown_turns=2,
                min_targets=1,
                max_targets=2,
                truth_metric_effects={
                    "escalation_pressure": 0.12,
                    "diplomatic_offramp": -0.03,
                },
                public_metric_effects={
                    "public_alarm": 0.18,
                    "market_anxiety": 0.12,
                    "allied_confidence": 0.05,
                },
                clock_effects={
                    "quarantine_incident_risk": 0.16,
                    "nuclear_escalation": 0.08,
                    "invasion_momentum": 0.06,
                },
                relationship_effects={"trust": -0.2},
                escalation_risk=0.5,
                deescalation_potential=0.15,
                information_outputs=[PayloadType.MILITARY_MOVEMENT_OBSERVATION],
                signal_reliability=0.95,
                signal_leak_risk=0.2,
                signal_distortion_risk=0.1,
                public_timeline_title="Naval Quarantine Announced",
                prompt_hints=[
                    "Use for blockade/quarantine/fleet cordon intent.",
                    "Creates strong pressure without immediate air strikes, but incidents become more likely.",
                ],
            ),
            ActionDefinition(
                action_id="authorize_recon_overflights",
                title="Authorize Reconnaissance Overflights",
                category=ActionCategory.INTELLIGENCE,
                actor_types_allowed=["player_faction"],
                targets_allowed=["opposing_faction"],
                channels_allowed=[SignalChannel.INTEL, SignalChannel.MILITARY],
                required_resources={"intelligence_focus": 1},
                resource_costs={"intelligence_focus": 1},
                min_targets=1,
                max_targets=2,
                truth_metric_effects={"missile_operational_progress": 0.02},
                public_metric_effects={"public_alarm": 0.03},
                clock_effects={
                    "command_and_control_risk": 0.08,
                    "nuclear_escalation": 0.03,
                },
                escalation_risk=0.28,
                information_outputs=[PayloadType.INTEL_REPORT],
                signal_reliability=0.88,
                signal_leak_risk=0.12,
                signal_distortion_risk=0.22,
                prompt_hints=[
                    "Use to keep tracking missile readiness.",
                    "Improves situational awareness in fiction but raises shootdown/misread risk.",
                ],
            ),
            ActionDefinition(
                action_id="raise_defcon_readiness",
                title="Raise Strategic Readiness",
                category=ActionCategory.MILITARY,
                actor_types_allowed=["player_faction"],
                targets_allowed=["opposing_faction"],
                channels_allowed=[SignalChannel.MILITARY],
                required_resources={"military_readiness": 1, "political_capital": 1},
                resource_costs={"political_capital": 1},
                actor_resource_effects={"military_readiness": -1},
                min_targets=1,
                max_targets=2,
                truth_metric_effects={"escalation_pressure": 0.12},
                public_metric_effects={"public_alarm": 0.1, "market_anxiety": 0.08},
                clock_effects={
                    "nuclear_escalation": 0.12,
                    "command_and_control_risk": 0.06,
                },
                relationship_effects={"trust": -0.15},
                escalation_risk=0.55,
                information_outputs=[PayloadType.MILITARY_MOVEMENT_OBSERVATION],
                signal_reliability=0.9,
                signal_leak_risk=0.18,
                signal_distortion_risk=0.12,
                prompt_hints=[
                    "Use for DEFCON/readiness signaling.",
                    "Deters but sharply raises nuclear signaling risk.",
                ],
            ),
            ActionDefinition(
                action_id="offer_non_invasion_pledge",
                title="Offer Non-Invasion Pledge",
                category=ActionCategory.DIPLOMATIC,
                actor_types_allowed=["player_faction"],
                targets_allowed=["opposing_faction"],
                channels_allowed=[SignalChannel.PRIVATE_DIPLOMATIC, SignalChannel.BACKCHANNEL],
                required_resources={"political_capital": 1},
                resource_costs={"political_capital": 1},
                min_targets=1,
                max_targets=2,
                truth_metric_effects={
                    "escalation_pressure": -0.08,
                    "diplomatic_offramp": 0.12,
                    "cuban_invasion_fear": -0.12,
                },
                clock_effects={
                    "backchannel_viability": 0.1,
                    "invasion_momentum": -0.08,
                    "nuclear_escalation": -0.05,
                },
                relationship_effects={"trust": 0.12},
                deescalation_potential=0.45,
                information_outputs=[PayloadType.PRIVATE_DIPLOMATIC_MESSAGE],
                signal_reliability=0.82,
                signal_leak_risk=0.14,
                signal_distortion_risk=0.16,
                prompt_hints=[
                    "Use for a private or semi-formal promise not to invade Cuba if missiles leave.",
                    "Most effective when paired with backchannel diplomacy.",
                ],
            ),
            ActionDefinition(
                action_id="secret_jupiter_trade",
                title="Float Secret Jupiter Missile Trade",
                category=ActionCategory.DIPLOMATIC,
                actor_types_allowed=["player_faction"],
                targets_allowed=["opposing_faction"],
                channels_allowed=[SignalChannel.BACKCHANNEL],
                required_resources={"political_capital": 2, "alliance_credit": 1},
                resource_costs={"political_capital": 2, "alliance_credit": 1},
                min_targets=1,
                max_targets=1,
                preconditions=["clock:backchannel_viability>=0.45"],
                truth_metric_effects={
                    "escalation_pressure": -0.12,
                    "diplomatic_offramp": 0.18,
                    "soviet_face_saving_need": -0.16,
                    "alliance_cohesion": -0.04,
                },
                public_metric_effects={"allied_confidence": -0.05},
                clock_effects={
                    "backchannel_viability": 0.12,
                    "nuclear_escalation": -0.08,
                    "invasion_momentum": -0.05,
                },
                relationship_effects={"trust": 0.18},
                deescalation_potential=0.6,
                information_outputs=[PayloadType.BACKCHANNEL_MESSAGE],
                signal_reliability=0.78,
                signal_leak_risk=0.22,
                signal_distortion_risk=0.18,
                prompt_hints=[
                    "Use for secret Turkey/Jupiter missile understanding.",
                    "Powerful off-ramp, but politically dangerous if leaked or made public.",
                ],
            ),
            ActionDefinition(
                action_id="prepare_air_strike",
                title="Prepare Air Strike Option",
                category=ActionCategory.MILITARY,
                actor_types_allowed=["player_faction"],
                targets_allowed=["opposing_faction"],
                channels_allowed=[SignalChannel.MILITARY],
                required_resources={"military_readiness": 3, "political_capital": 2},
                resource_costs={"political_capital": 2},
                actor_resource_effects={"military_readiness": -2},
                preparation_turns=1,
                cooldown_turns=3,
                min_targets=1,
                max_targets=2,
                truth_metric_effects={"escalation_pressure": 0.18, "diplomatic_offramp": -0.12},
                public_metric_effects={"public_alarm": 0.14, "market_anxiety": 0.12},
                clock_effects={
                    "nuclear_escalation": 0.18,
                    "command_and_control_risk": 0.14,
                    "invasion_momentum": 0.18,
                    "backchannel_viability": -0.12,
                },
                relationship_effects={"trust": -0.28},
                escalation_risk=0.75,
                information_outputs=[PayloadType.MILITARY_MOVEMENT_OBSERVATION],
                signal_reliability=0.82,
                signal_leak_risk=0.28,
                signal_distortion_risk=0.2,
                prompt_hints=[
                    "Use for bombing/strike/invasion preparation.",
                    "High leverage and high escalation risk.",
                ],
            ),
            ActionDefinition(
                action_id="soviet_probe_compromise",
                title="Probe Compromise Terms",
                category=ActionCategory.DIPLOMATIC,
                actor_types_allowed=["opposing_faction"],
                targets_allowed=["player_faction"],
                channels_allowed=[SignalChannel.BACKCHANNEL, SignalChannel.PRIVATE_DIPLOMATIC],
                required_resources={"diplomatic_flexibility": 1},
                resource_costs={"diplomatic_flexibility": 1},
                min_targets=1,
                max_targets=1,
                truth_metric_effects={"diplomatic_offramp": 0.09, "escalation_pressure": -0.04},
                clock_effects={"backchannel_viability": 0.08, "nuclear_escalation": -0.03},
                relationship_effects={"trust": 0.1},
                deescalation_potential=0.35,
                information_outputs=[PayloadType.BACKCHANNEL_MESSAGE],
                signal_reliability=0.8,
                signal_leak_risk=0.12,
                signal_distortion_risk=0.18,
                prompt_hints=[
                    "Soviet use: test a deal around non-invasion or Jupiter missiles.",
                ],
            ),
            ActionDefinition(
                action_id="soviet_public_defiance",
                title="Issue Soviet Public Defiance",
                category=ActionCategory.INFORMATION,
                actor_types_allowed=["opposing_faction"],
                targets_allowed=["player_faction"],
                channels_allowed=[SignalChannel.PUBLIC],
                required_resources={"political_capital": 1},
                resource_costs={"political_capital": 1},
                min_targets=1,
                truth_metric_effects={"escalation_pressure": 0.07, "diplomatic_offramp": -0.04},
                public_metric_effects={"public_alarm": 0.1, "market_anxiety": 0.08},
                clock_effects={"nuclear_escalation": 0.06, "backchannel_viability": -0.04},
                relationship_effects={"trust": -0.14},
                escalation_risk=0.38,
                information_outputs=[PayloadType.PUBLIC_STATEMENT],
                public_timeline_title="Soviet Public Defiance",
                prompt_hints=[
                    "Soviet/Cuban use: public denial, accusation, or refusal under pressure.",
                ],
            ),
            ActionDefinition(
                action_id="cuban_air_defense_alert",
                title="Raise Cuban Air Defense Alert",
                category=ActionCategory.MILITARY,
                actor_types_allowed=["opposing_faction"],
                targets_allowed=["player_faction"],
                channels_allowed=[SignalChannel.MILITARY],
                required_resources={"air_defense_control": 1},
                resource_costs={"air_defense_control": 1},
                min_targets=1,
                max_targets=1,
                truth_metric_effects={"escalation_pressure": 0.1, "cuban_invasion_fear": 0.05},
                public_metric_effects={"public_alarm": 0.06},
                clock_effects={
                    "command_and_control_risk": 0.14,
                    "nuclear_escalation": 0.08,
                },
                relationship_effects={"trust": -0.12},
                escalation_risk=0.55,
                information_outputs=[PayloadType.MILITARY_MOVEMENT_OBSERVATION],
                signal_reliability=0.8,
                signal_leak_risk=0.18,
                signal_distortion_risk=0.24,
                prompt_hints=[
                    "Cuban use: air defense alert, local readiness, risk of U-2 shootdown.",
                ],
            ),
            ActionDefinition(
                action_id="nato_reassurance_request",
                title="Request Allied Reassurance",
                category=ActionCategory.DIPLOMATIC,
                actor_types_allowed=["allied_faction"],
                targets_allowed=["player_faction"],
                channels_allowed=[SignalChannel.PRIVATE_DIPLOMATIC],
                required_resources={"alliance_credit": 1},
                resource_costs={"alliance_credit": 1},
                min_targets=1,
                max_targets=1,
                truth_metric_effects={"alliance_cohesion": 0.04},
                public_metric_effects={"allied_confidence": 0.03},
                clock_effects={"backchannel_viability": 0.02},
                relationship_effects={"trust": 0.08},
                deescalation_potential=0.1,
                information_outputs=[PayloadType.PRIVATE_DIPLOMATIC_MESSAGE],
                signal_reliability=0.86,
                signal_leak_risk=0.1,
                signal_distortion_risk=0.12,
                prompt_hints=[
                    "NATO use: private request for consultation, support, or reassurance.",
                ],
            ),
        ],
    )


def _cuban_scenario_events() -> list[ScenarioEventDefinition]:
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
                required_any_action_ids=["announce_quarantine"],
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
            related_action_ids=["announce_quarantine"],
            problem_title="Quarantine contact nearing the line",
            problem_summary=(
                "Naval contact reports are urgent but imperfect; a public order may "
                "now collide with local command decisions."
            ),
            urgency="high",
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
                    "authorize_recon_overflights",
                    "cuban_air_defense_alert",
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
            related_action_ids=["authorize_recon_overflights", "cuban_air_defense_alert"],
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
                    "secret_jupiter_trade",
                    "offer_non_invasion_pledge",
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
            related_action_ids=["secret_jupiter_trade", "offer_non_invasion_pledge"],
            problem_title="Allied confidence is strained",
            problem_summary=(
                "Private bargaining can help end the crisis, but allied governments "
                "may punish Washington if they learn the settlement late."
            ),
            urgency="medium",
        ),
    ]


def _initial_us_excomm_advisor_council() -> AdvisorCouncilState:
    return AdvisorCouncilState(
        player_entity_id="us_excomm",
        advisors={
            "state": AdvisorState(
                advisor_id="state",
                name="State",
                portfolio="Diplomacy and alliance signaling",
                personality="Measured, legalistic, face-saving, sensitive to alliance politics.",
                institutional_orientation="Diplomatic settlement through credible restraint.",
                trust_player=0.62,
                trust_channels={
                    "backchannel": 0.75,
                    "private_diplomatic": 0.82,
                    "public": 0.55,
                    "military": 0.35,
                    "intel": 0.58,
                },
                paranoia=0.38,
                urgency=0.42,
                corruption=0.08,
                institutional_confidence=0.7,
                beliefs={
                    "face_saving": AdvisorBelief(
                        topic="face_saving",
                        value=0.74,
                        summary="Moscow needs a withdrawal path that does not look like public humiliation.",
                        confidence=0.64,
                    )
                },
            ),
            "defense": AdvisorState(
                advisor_id="defense",
                name="Defense",
                portfolio="Military posture and operational readiness",
                personality="Direct, impatient with ambiguity, focused on credible force.",
                institutional_orientation="Use bounded military pressure to keep initiative.",
                trust_player=0.56,
                trust_channels={
                    "military": 0.85,
                    "intel": 0.68,
                    "public": 0.58,
                    "backchannel": 0.34,
                    "private_diplomatic": 0.44,
                },
                paranoia=0.52,
                urgency=0.76,
                corruption=0.05,
                institutional_confidence=0.74,
                beliefs={
                    "delay_risk": AdvisorBelief(
                        topic="delay_risk",
                        value=0.78,
                        summary="Delay may let missile sites become operational and narrow later options.",
                        confidence=0.66,
                    )
                },
            ),
            "intelligence": AdvisorState(
                advisor_id="intelligence",
                name="Intelligence",
                portfolio="Reconnaissance, uncertainty, and adversary intent",
                personality="Skeptical, detail-oriented, wary of false certainty.",
                institutional_orientation="Reduce uncertainty before irreversible choices.",
                trust_player=0.58,
                trust_channels={
                    "intel": 0.88,
                    "backchannel": 0.55,
                    "private_diplomatic": 0.5,
                    "public": 0.4,
                    "military": 0.52,
                },
                paranoia=0.72,
                urgency=0.57,
                corruption=0.03,
                institutional_confidence=0.62,
                beliefs={
                    "command_control": AdvisorBelief(
                        topic="command_control",
                        value=0.62,
                        summary="Local Cuban and Soviet command discipline is a serious uncertainty.",
                        confidence=0.58,
                    )
                },
            ),
            "political": AdvisorState(
                advisor_id="political",
                name="Political",
                portfolio="Domestic legitimacy and public coalition management",
                personality="Pragmatic, reputation-aware, anxious about leaks and public reversals.",
                institutional_orientation="Maintain domestic support without closing private options.",
                trust_player=0.54,
                trust_channels={
                    "public": 0.78,
                    "private_diplomatic": 0.54,
                    "backchannel": 0.42,
                    "military": 0.5,
                    "intel": 0.47,
                },
                paranoia=0.56,
                urgency=0.61,
                corruption=0.18,
                institutional_confidence=0.58,
                beliefs={
                    "public_alarm": AdvisorBelief(
                        topic="public_alarm",
                        value=0.58,
                        summary="The public can tolerate pressure if the administration explains the stakes.",
                        confidence=0.6,
                    )
                },
            ),
            "legal_un": AdvisorState(
                advisor_id="legal_un",
                name="Legal/UN",
                portfolio="International law, UN posture, and legitimacy optics",
                personality="Cautious, procedural, sensitive to precedent and neutral opinion.",
                institutional_orientation="Build legitimacy before visible coercion.",
                trust_player=0.6,
                trust_channels={
                    "public": 0.72,
                    "private_diplomatic": 0.64,
                    "backchannel": 0.52,
                    "military": 0.28,
                    "intel": 0.46,
                },
                paranoia=0.44,
                urgency=0.48,
                corruption=0.04,
                institutional_confidence=0.69,
                beliefs={
                    "legitimacy": AdvisorBelief(
                        topic="legitimacy",
                        value=0.7,
                        summary="OAS and UN framing can make pressure look controlled rather than unilateral.",
                        confidence=0.63,
                    )
                },
            ),
        },
    )
