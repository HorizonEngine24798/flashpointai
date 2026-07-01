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
            truth_metric_minimums={"diplomatic_offramp": 0.72},
            hidden_clock_maximums={"nuclear_escalation": 0.58},
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
