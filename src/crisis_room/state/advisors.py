from __future__ import annotations

from pydantic import BaseModel, Field


class AdvisorBelief(BaseModel):
    topic: str
    value: float = Field(default=0.5, ge=0.0, le=1.0)
    summary: str = ""
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    last_updated_turn: int = 0


class AdvisorState(BaseModel):
    advisor_id: str
    name: str
    portfolio: str
    personality: str
    institutional_orientation: str = ""
    hidden_metric_access: bool = False
    loyal_to_player: bool = False

    trust_player: float = Field(default=0.5, ge=0.0, le=1.0)
    trust_advisors: dict[str, float] = Field(default_factory=dict)
    trust_channels: dict[str, float] = Field(default_factory=dict)

    paranoia: float = Field(default=0.5, ge=0.0, le=1.0)
    urgency: float = Field(default=0.5, ge=0.0, le=1.0)
    institutional_confidence: float = Field(default=0.5, ge=0.0, le=1.0)

    beliefs: dict[str, AdvisorBelief] = Field(default_factory=dict)
    memory_summary: str = ""
    recent_recommendations: list[str] = Field(default_factory=list)
    recent_embarrassments: list[str] = Field(default_factory=list)


class AdvisorCouncilState(BaseModel):
    player_entity_id: str
    advisors: dict[str, AdvisorState] = Field(default_factory=dict)


class AdvisorStateDelta(BaseModel):
    advisor_id: str
    trust_player_delta: float = Field(default=0.0, ge=-1.0, le=1.0)
    paranoia_delta: float = Field(default=0.0, ge=-1.0, le=1.0)
    urgency_delta: float = Field(default=0.0, ge=-1.0, le=1.0)
    institutional_confidence_delta: float = Field(default=0.0, ge=-1.0, le=1.0)
    trust_channel_deltas: dict[str, float] = Field(default_factory=dict)
    belief_value_deltas: dict[str, float] = Field(default_factory=dict)
    belief_summaries: dict[str, str] = Field(default_factory=dict)
    memory_notes: list[str] = Field(default_factory=list)
    recommendation_notes: list[str] = Field(default_factory=list)
    embarrassment_notes: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    summary: str = ""


class AdvisorCouncilUpdate(BaseModel):
    player_entity_id: str
    turn_number: int = Field(ge=0)
    deltas: list[AdvisorStateDelta] = Field(default_factory=list)
    summary: list[str] = Field(default_factory=list)
