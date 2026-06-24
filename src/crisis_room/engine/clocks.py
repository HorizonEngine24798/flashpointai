from __future__ import annotations

from pydantic import BaseModel, Field


class NumericChange(BaseModel):
    key: str
    before: float
    delta: float
    after: float


def apply_numeric_effects(
    values: dict[str, float],
    effects: dict[str, int | float],
    *,
    floor: float = 0.0,
    ceiling: float = 1.0,
) -> list[NumericChange]:
    changes: list[NumericChange] = []
    for key, raw_delta in effects.items():
        delta = float(raw_delta)
        before = float(values.get(key, 0.0))
        after = round(clamp(before + delta, floor, ceiling), 10)
        values[key] = after
        changes.append(NumericChange(key=key, before=before, delta=delta, after=after))
    return changes


def clamp(value: float, floor: float = 0.0, ceiling: float = 1.0) -> float:
    return max(floor, min(ceiling, value))


class ClockThreshold(BaseModel):
    clock_id: str
    threshold: float = Field(ge=0.0, le=1.0)
    outcome_id: str


def crossed_thresholds(
    clocks: dict[str, float],
    thresholds: list[ClockThreshold],
) -> list[ClockThreshold]:
    return [
        threshold
        for threshold in thresholds
        if clocks.get(threshold.clock_id, 0.0) >= threshold.threshold
    ]
