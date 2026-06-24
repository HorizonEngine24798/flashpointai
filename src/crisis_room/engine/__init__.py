"""Deterministic engine."""

from crisis_room.engine.actions import ActionDefinition, ActionPackage

__all__ = [
    "ActionDefinition",
    "ActionPackage",
    "CausalTraceEntry",
    "DeterministicEngineV2",
    "DeterministicTurnResult",
    "FakeDeterministicEngine",
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
