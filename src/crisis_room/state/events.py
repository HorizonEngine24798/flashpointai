from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class ScenarioEventStatus(str, Enum):
    ACTIVE = "active"
    EXPIRED = "expired"


class ScenarioEventRecord(BaseModel):
    event_id: str
    title: str
    summary: str
    kind: str = "scenario"
    turn_number: int = Field(ge=0)
    status: ScenarioEventStatus = ScenarioEventStatus.ACTIVE
    expires_turn: int | None = Field(default=None, ge=0)
    urgency: str = "medium"
    visible_to: list[str] = Field(default_factory=list)
    related_entity_ids: list[str] = Field(default_factory=list)
    related_action_ids: list[str] = Field(default_factory=list)
    problem_title: str = ""
    problem_summary: str = ""
    effect_summary: list[str] = Field(default_factory=list)
    signal_ids: list[str] = Field(default_factory=list)
    public: bool = False
    metadata: dict[str, str | int | float | bool] = Field(default_factory=dict)

    def active_for(self, turn_number: int, viewer_entity_id: str | None = None) -> bool:
        if self.status != ScenarioEventStatus.ACTIVE:
            return False
        if self.expires_turn is not None and turn_number > self.expires_turn:
            return False
        return not self.visible_to or viewer_entity_id is None or viewer_entity_id in self.visible_to
