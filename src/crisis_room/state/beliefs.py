from __future__ import annotations

from pydantic import BaseModel, Field


class BeliefClaim(BaseModel):
    """An entity-local belief about the crisis, not omniscient truth."""

    topic: str
    summary: str
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    source_signal_ids: list[str] = Field(default_factory=list)
    last_updated_turn: int = Field(default=0, ge=0)


class BeliefState(BaseModel):
    summary: str = ""
    claims: dict[str, BeliefClaim] = Field(default_factory=dict)
    uncertainty_notes: list[str] = Field(default_factory=list)
    last_updated_turn: int = Field(default=0, ge=0)

    def upsert_claim(self, claim: BeliefClaim) -> None:
        self.claims[claim.topic] = claim
        self.last_updated_turn = max(self.last_updated_turn, claim.last_updated_turn)


class InternalNarrative(BaseModel):
    narrative_id: str
    name: str
    worldview: str
    preferred_strategy: str
    fear: str
    red_lines: list[str] = Field(default_factory=list)
    current_argument: str = ""
    influence_weight: float = Field(default=0.5, ge=0.0, le=1.0)
    recent_wins: list[str] = Field(default_factory=list)
    recent_losses: list[str] = Field(default_factory=list)
