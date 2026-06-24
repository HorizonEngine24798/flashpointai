from __future__ import annotations

from typing import Protocol

from crisis_room.engine.actions import ActionPackage, ActionValidationResult
from crisis_room.engine.adjudication import DeterministicTurnResult
from crisis_room.state.world import WorldStateV2


class DeterministicEngine(Protocol):
    def validate_action(
        self,
        world_state: WorldStateV2,
        action_package: ActionPackage,
    ) -> ActionValidationResult:
        """Check authority, resources, preconditions, timing, and target legality."""

    def resolve_actions(
        self,
        world_state: WorldStateV2,
        action_packages: list[ActionPackage],
    ) -> DeterministicTurnResult:
        """Apply legal deterministic action effects and produce routing signals."""
