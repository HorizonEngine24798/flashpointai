from __future__ import annotations

from crisis_room.scenario.endings import ScenarioEndingDefinition


def cuban_scenario_endings() -> list[ScenarioEndingDefinition]:
    return [
        ScenarioEndingDefinition(
            ending_id="nuclear_exchange",
            title="Nuclear Exchange",
            summary=(
                "The crisis has crossed the threshold where national leaders can no "
                "longer keep nuclear escalation under political control."
            ),
            priority=100,
            hidden_clock_minimums={"nuclear_escalation": 0.9},
            related_entity_ids=["us_excomm", "soviet_presidium", "cuba", "nato_allies"],
            urgency="critical",
            public_timeline_title="Nuclear War Erupts",
            public_timeline_summary=(
                "Public reporting collapses into emergency bulletins as the crisis "
                "becomes a nuclear exchange."
            ),
            final_summary=(
                "The Cuban Missile Crisis ends in nuclear war. The final record is "
                "defined less by policy victory than by the failure of leaders, "
                "local command systems, and public pressure to keep violence bounded."
            ),
        ),
        ScenarioEndingDefinition(
            ending_id="settlement_reached",
            title="Settlement Reached",
            summary=(
                "A credible off-ramp now exists: Moscow can remove the missiles, "
                "Washington can avoid invasion, and the most dangerous clocks have slowed."
            ),
            priority=80,
            truth_metric_minimums={"diplomatic_offramp": 0.82},
            hidden_clock_maximums={"nuclear_escalation": 0.5},
            required_active_commitments=["settlement_framework_offered"],
            related_entity_ids=["us_excomm", "soviet_presidium", "cuba", "nato_allies"],
            urgency="high",
            public_timeline_title="Crisis Settlement Takes Shape",
            public_timeline_summary=(
                "Public statements suggest a diplomatic settlement is beginning to "
                "take shape around restraint and missile withdrawal."
            ),
            final_summary=(
                "The Cuban Missile Crisis ends with a negotiated settlement. The "
                "public record centers on restraint and missile withdrawal, while "
                "private bargains, allied confidence, and Cuban security fears shape "
                "how stable the settlement feels afterward."
            ),
        ),
        ScenarioEndingDefinition(
            ending_id="hardline_takeover",
            title="Hardline Takeover",
            summary=(
                "The crisis room is displaced by a hardline faction that treats "
                "compromise as collapse."
            ),
            priority=70,
            truth_metric_minimums={
                "hawk_pressure": 0.85,
                "perceived_weakness": 0.75,
                "institutional_loyalty": 0.0,
            },
            truth_metric_maximums={"institutional_loyalty": 0.35},
            public_metric_minimums={"public_confidence": 0.55},
            related_entity_ids=["us_excomm"],
            urgency="critical",
            public_timeline_title="Security Faction Seizes Crisis Line",
            public_timeline_summary=(
                "Officials signal a harder Cuba line as compromise loses room "
                "inside Washington."
            ),
            final_summary=(
                "The player kept pressure alive abroad but lost control of the "
                "institutional coalition at home."
            ),
        ),
        ScenarioEndingDefinition(
            ending_id="ousted",
            title="Ousted",
            summary=(
                "The player keeps the international crisis alive but loses "
                "authority at home."
            ),
            priority=65,
            truth_metric_maximums={
                "domestic_trust": 0.15,
                "institutional_loyalty": 0.25,
            },
            related_entity_ids=["us_excomm"],
            urgency="critical",
            public_timeline_title="White House Authority Buckles",
            public_timeline_summary=(
                "Domestic actors openly challenge the administration's control "
                "of the Cuba crisis."
            ),
            final_summary=(
                "The crisis does not end in immediate war, but domestic authority "
                "collapses before policy can regain legitimacy."
            ),
        ),
        ScenarioEndingDefinition(
            ending_id="media_collapse",
            title="Media Collapse",
            summary=(
                "The public information environment collapses faster than policy "
                "can regain legitimacy."
            ),
            priority=60,
            truth_metric_maximums={"domestic_trust": 0.25},
            public_metric_minimums={"press_alarm": 0.9},
            related_entity_ids=["us_excomm"],
            urgency="critical",
            public_timeline_title="Crisis Messaging Breaks Down",
            public_timeline_summary=(
                "Conflicting accounts overwhelm the administration's public line."
            ),
            final_summary=(
                "The crisis remains politically unmanageable as public information "
                "collapses into rumor, leak, and factional blame."
            ),
        ),
        ScenarioEndingDefinition(
            ending_id="unstable_continuation",
            title="Unstable Continuation",
            summary=(
                "The immediate danger has not become nuclear war, but the crisis is "
                "settling into an unstable continuation with too many issues unresolved."
            ),
            priority=10,
            min_turn=6,
            truth_metric_maximums={"diplomatic_offramp": 0.68},
            hidden_clock_maximums={"nuclear_escalation": 0.89},
            related_entity_ids=["us_excomm", "soviet_presidium", "cuba", "nato_allies"],
            urgency="medium",
            final_summary=(
                "The Cuban Missile Crisis does not cleanly resolve. Leaders avoid "
                "immediate nuclear exchange, but unresolved missiles, local command "
                "risk, alliance politics, and private-channel fragility leave the "
                "timeline open and dangerous."
            ),
        ),
    ]
