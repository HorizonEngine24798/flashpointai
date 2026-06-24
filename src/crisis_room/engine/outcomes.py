from __future__ import annotations

from pydantic import BaseModel, Field

from crisis_room.engine.clocks import ClockThreshold, crossed_thresholds
from crisis_room.state.world import WorldStateV2


class OutcomeDefinition(BaseModel):
    outcome_id: str
    title: str
    description: str
    clock_thresholds: list[ClockThreshold] = Field(default_factory=list)
    truth_metric_minimums: dict[str, float] = Field(default_factory=dict)
    public_metric_minimums: dict[str, float] = Field(default_factory=dict)
    terminal: bool = False


class OutcomeEvaluation(BaseModel):
    triggered: list[OutcomeDefinition] = Field(default_factory=list)

    @property
    def terminal(self) -> bool:
        return any(outcome.terminal for outcome in self.triggered)


def evaluate_outcomes(
    world_state: WorldStateV2,
    outcomes: list[OutcomeDefinition],
) -> OutcomeEvaluation:
    triggered: list[OutcomeDefinition] = []
    for outcome in outcomes:
        if _outcome_triggered(world_state, outcome):
            triggered.append(outcome)
    return OutcomeEvaluation(triggered=triggered)


def _outcome_triggered(world_state: WorldStateV2, outcome: OutcomeDefinition) -> bool:
    if outcome.clock_thresholds:
        crossed = crossed_thresholds(world_state.hidden_clocks, outcome.clock_thresholds)
        if len(crossed) != len(outcome.clock_thresholds):
            return False
    for key, minimum in outcome.truth_metric_minimums.items():
        if world_state.truth_metrics.get(key, 0.0) < minimum:
            return False
    for key, minimum in outcome.public_metric_minimums.items():
        if world_state.public_metrics.get(key, 0.0) < minimum:
            return False
    return bool(
        outcome.clock_thresholds
        or outcome.truth_metric_minimums
        or outcome.public_metric_minimums
    )
