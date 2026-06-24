from __future__ import annotations

from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


class SignalChannel(str, Enum):
    PUBLIC = "public"
    PRIVATE_DIPLOMATIC = "private_diplomatic"
    BACKCHANNEL = "backchannel"
    INTEL = "intel"
    MEDIA = "media"
    MILITARY = "military"
    ECONOMIC = "economic"
    HUMANITARIAN = "humanitarian"
    RUMOR = "rumor"
    GAMEMASTER = "gamemaster"


class PayloadType(str, Enum):
    PUBLIC_STATEMENT = "public_statement"
    PRIVATE_DIPLOMATIC_MESSAGE = "private_diplomatic_message"
    BACKCHANNEL_MESSAGE = "backchannel_message"
    INTEL_REPORT = "intel_report"
    MEDIA_REPORT = "media_report"
    MILITARY_MOVEMENT_OBSERVATION = "military_movement_observation"
    ECONOMIC_SIGNAL = "economic_signal"
    HUMANITARIAN_REPORT = "humanitarian_report"
    RUMOR = "rumor"
    EVENT_NOTICE = "event_notice"
    GAMEMASTER_RULING = "gamemaster_ruling"


class SignalVisibility(str, Enum):
    PUBLIC = "public"
    PRIVATE = "private"
    COVERT = "covert"
    SECRET = "secret"


class Signal(BaseModel):
    signal_id: str = Field(default_factory=lambda: str(uuid4()))
    source_entity_id: str
    recipient_entity_ids: list[str] = Field(default_factory=list)
    channel: SignalChannel
    payload_type: PayloadType
    content: str
    truth_reference_id: str | None = None
    emitted_turn: int = Field(ge=0)
    intended_arrival_turn: int = Field(ge=0)
    visibility: SignalVisibility = SignalVisibility.PRIVATE
    reliability: float = Field(default=1.0, ge=0.0, le=1.0)
    deniability: float = Field(default=0.0, ge=0.0, le=1.0)
    leak_risk: float = Field(default=0.0, ge=0.0, le=1.0)
    distortion_risk: float = Field(default=0.0, ge=0.0, le=1.0)
    urgency: float = Field(default=0.5, ge=0.0, le=1.0)
    classification: str = "unclassified"
    metadata: dict[str, str | int | float | bool] = Field(default_factory=dict)

    @property
    def is_public(self) -> bool:
        return self.visibility == SignalVisibility.PUBLIC or self.channel in {
            SignalChannel.PUBLIC,
            SignalChannel.MEDIA,
        }


class SignalDelivery(BaseModel):
    delivery_id: str = Field(default_factory=lambda: str(uuid4()))
    signal_id: str
    recipient_entity_id: str
    source_entity_id: str
    arrived_turn: int = Field(ge=0)
    channel: SignalChannel
    payload_type: PayloadType
    observed_content: str
    observed_reliability: float = Field(default=1.0, ge=0.0, le=1.0)
    visibility: SignalVisibility
    classification: str = "unclassified"
    distortion_applied: bool = False
    contradiction_applied: bool = False
    leak_applied: bool = False
    delivery_notes: list[str] = Field(default_factory=list)
