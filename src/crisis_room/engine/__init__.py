"""Deterministic engine."""

from crisis_room.engine.actions import (
    ActionDefinition,
    ActionPackage,
    ActionResolver,
    CapabilityParameter,
    CapabilityParameterKind,
    ScenarioCapability,
)

__all__ = [
    "ActionDefinition",
    "ActionPackage",
    "ActionResolver",
    "CausalTraceEntry",
    "CapabilityParameter",
    "CapabilityParameterKind",
    "DeterministicEngineV2",
    "DeterministicTurnResult",
    "FakeDeterministicEngine",
    "ScenarioCapability",
]


def __getattr__(name: str) -> object:
    if name in {
        "CausalTraceEntry",
        "DeterministicEngineV2",
        "DeterministicTurnResult",
        "FakeDeterministicEngine",
    }:
        from crisis_room.engine import adjudication

        return getattr(adjudication, name)
    raise AttributeError(name)
