from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class EndingOfferStatus(str, Enum):
    OFFERED = "offered"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class EndingOfferRecord(BaseModel):
    offer_id: str
    ending_id: str
    title: str
    summary: str
    turn_number: int = Field(ge=0)
    status: EndingOfferStatus = EndingOfferStatus.OFFERED
    visible_to: list[str] = Field(default_factory=list)
    event_record_id: str = ""
    final_summary: str = ""
    accepted_turn: int | None = Field(default=None, ge=0)
    rejected_turn: int | None = Field(default=None, ge=0)
    reoffer_after_turn: int | None = Field(default=None, ge=0)
    metadata: dict[str, str | int | float | bool] = Field(default_factory=dict)

    def active_for(self, turn_number: int, viewer_entity_id: str | None = None) -> bool:
        if self.status != EndingOfferStatus.OFFERED:
            return False
        if self.turn_number > turn_number:
            return False
        return (
            not self.visible_to
            or viewer_entity_id is None
            or viewer_entity_id in self.visible_to
        )
