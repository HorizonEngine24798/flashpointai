from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from crisis_room.state.signals import SignalChannel


class ScenarioEventStatus(str, Enum):
    ACTIVE = "active"
    EXPIRED = "expired"


class ScenarioEventChoiceStatus(str, Enum):
    PENDING = "pending"
    RESOLVED = "resolved"
    EXPIRED = "expired"


class EventChoiceOption(BaseModel):
    option_id: str
    label: str
    summary: str = ""
    action_id: str
    capability_id: str
    target_ids: list[str] = Field(default_factory=list)
    channel: SignalChannel = SignalChannel.PRIVATE_DIPLOMATIC
    parameters: dict[str, str | int | float | bool | list[str]] = Field(default_factory=dict)
    consumes_normal_action_budget: bool = True
    event_only_extra_budget: int = Field(default=0, ge=0)


class ScenarioEventChoiceRecord(BaseModel):
    choice_id: str
    event_id: str
    title: str
    prompt: str
    turn_number: int = Field(ge=0)
    status: ScenarioEventChoiceStatus = ScenarioEventChoiceStatus.PENDING
    expires_turn: int | None = Field(default=None, ge=0)
    visible_to: list[str] = Field(default_factory=list)
    options: list[EventChoiceOption] = Field(default_factory=list)
    selected_option_id: str = ""
    metadata: dict[str, str | int | float | bool] = Field(default_factory=dict)

    def active_for(self, turn_number: int, viewer_entity_id: str | None = None) -> bool:
        if self.status != ScenarioEventChoiceStatus.PENDING:
            return False
        if self.expires_turn is not None and turn_number > self.expires_turn:
            return False
        return not self.visible_to or viewer_entity_id is None or viewer_entity_id in self.visible_to


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
    choice_ids: list[str] = Field(default_factory=list)
    public: bool = False
    metadata: dict[str, str | int | float | bool] = Field(default_factory=dict)

    def active_for(self, turn_number: int, viewer_entity_id: str | None = None) -> bool:
        if self.status != ScenarioEventStatus.ACTIVE:
            return False
        if self.expires_turn is not None and turn_number > self.expires_turn:
            return False
        return not self.visible_to or viewer_entity_id is None or viewer_entity_id in self.visible_to
