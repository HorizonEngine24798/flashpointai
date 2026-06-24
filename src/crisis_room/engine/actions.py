from __future__ import annotations

from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field

from crisis_room.state.signals import PayloadType, SignalChannel


class ActionCategory(str, Enum):
    DIPLOMATIC = "diplomatic"
    MILITARY = "military"
    INTELLIGENCE = "intelligence"
    ECONOMIC = "economic"
    DOMESTIC = "domestic"
    HUMANITARIAN = "humanitarian"
    INFORMATION = "information"
    GAMEMASTER = "gamemaster"


class ActionDefinition(BaseModel):
    action_id: str
    title: str
    category: ActionCategory
    actor_types_allowed: list[str] = Field(default_factory=list)
    targets_allowed: list[str] = Field(default_factory=list)
    channels_allowed: list[SignalChannel] = Field(default_factory=list)
    required_resources: dict[str, int] = Field(default_factory=dict)
    resource_costs: dict[str, int] = Field(default_factory=dict)
    actor_resource_effects: dict[str, int] = Field(default_factory=dict)
    target_resource_effects: dict[str, int] = Field(default_factory=dict)
    preparation_turns: int = Field(default=0, ge=0)
    execution_turns: int = Field(default=1, ge=0)
    cooldown_turns: int = Field(default=0, ge=0)
    min_targets: int = Field(default=0, ge=0)
    max_targets: int | None = Field(default=None, ge=0)
    preconditions: list[str] = Field(default_factory=list)
    direct_effects: dict[str, int | float | str | bool] = Field(default_factory=dict)
    side_effects: list[str] = Field(default_factory=list)
    truth_metric_effects: dict[str, float] = Field(default_factory=dict)
    public_metric_effects: dict[str, float] = Field(default_factory=dict)
    clock_effects: dict[str, int | float] = Field(default_factory=dict)
    relationship_effects: dict[str, float] = Field(default_factory=dict)
    escalation_risk: float = Field(default=0.0, ge=0.0, le=1.0)
    deescalation_potential: float = Field(default=0.0, ge=0.0, le=1.0)
    information_outputs: list[PayloadType] = Field(default_factory=list)
    signal_reliability: float = Field(default=1.0, ge=0.0, le=1.0)
    signal_leak_risk: float = Field(default=0.0, ge=0.0, le=1.0)
    signal_distortion_risk: float = Field(default=0.0, ge=0.0, le=1.0)
    public_timeline_title: str | None = None
    omniscient_timeline_title: str | None = None
    prompt_hints: list[str] = Field(default_factory=list)


class ActionPackage(BaseModel):
    package_id: str = Field(default_factory=lambda: str(uuid4()))
    actor_id: str
    action_id: str
    target_ids: list[str] = Field(default_factory=list)
    channel: SignalChannel = SignalChannel.PRIVATE_DIPLOMATIC
    intent_summary: str
    public_rationale: str = ""
    private_rationale: str = ""
    requested_timing: str = "current_turn"
    commitment_level: float = Field(default=0.5, ge=0.0, le=1.0)
    risk_acceptance: float = Field(default=0.5, ge=0.0, le=1.0)
    fallback_condition: str | None = None
    submitted_turn: int | None = Field(default=None, ge=0)
    metadata: dict[str, str | int | float | bool] = Field(default_factory=dict)


class ActionValidationResult(BaseModel):
    is_valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    action_definition_id: str | None = None
