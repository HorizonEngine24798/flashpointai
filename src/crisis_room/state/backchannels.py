from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class BackchannelThreadStatus(str, Enum):
    OPEN = "open"
    EXPIRED = "expired"


class BackchannelMessageRecord(BaseModel):
    record_id: str
    turn_number: int = Field(ge=0)
    sender_entity_id: str
    recipient_entity_ids: list[str] = Field(default_factory=list)
    action_id: str
    action_package_id: str
    summary: str
    reliability: float = Field(default=1.0, ge=0.0, le=1.0)
    leak_risk: float = Field(default=0.0, ge=0.0, le=1.0)


class BackchannelThread(BaseModel):
    thread_id: str
    participant_entity_ids: list[str] = Field(default_factory=list)
    player_entity_id: str = ""
    opened_turn: int = Field(ge=0)
    last_active_turn: int = Field(ge=0)
    expires_turn: int = Field(ge=0)
    status: BackchannelThreadStatus = BackchannelThreadStatus.OPEN
    trust_level: float = Field(default=0.5, ge=0.0, le=1.0)
    leak_risk: float = Field(default=0.1, ge=0.0, le=1.0)
    max_player_messages: int = Field(default=1, ge=0)
    player_messages_used: int = Field(default=0, ge=0)
    player_message_turn: int = Field(default=0, ge=0)
    message_records: list[BackchannelMessageRecord] = Field(default_factory=list)
    metadata: dict[str, str | int | float | bool] = Field(default_factory=dict)

    @property
    def player_messages_remaining(self) -> int:
        return max(0, self.max_player_messages - self.player_messages_used)

    def player_messages_remaining_for_turn(self, turn_number: int) -> int:
        used = self.player_messages_used if self.player_message_turn == turn_number else 0
        return max(0, self.max_player_messages - used)


class BackchannelThreadUpdate(BaseModel):
    turn_number: int = Field(ge=0)
    opened_thread_ids: list[str] = Field(default_factory=list)
    refreshed_thread_ids: list[str] = Field(default_factory=list)
    expired_thread_ids: list[str] = Field(default_factory=list)
    message_record_ids: list[str] = Field(default_factory=list)
    summary: list[str] = Field(default_factory=list)
