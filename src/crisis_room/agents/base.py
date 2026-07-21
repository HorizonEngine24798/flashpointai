from __future__ import annotations

from pydantic import BaseModel, Field

from crisis_room.engine.actions import ActionPackage
from crisis_room.state.signals import Signal
from crisis_room.state.timelines import TimelineEntry


class AgentOutput(BaseModel):
    entity_id: str
    perception_summary: str = ""
    action_package: ActionPackage | None = None
    public_timeline_delta: list[TimelineEntry] = Field(default_factory=list)
    emitted_signals: list[Signal] = Field(default_factory=list)
    raw_llm_outputs: list[dict[str, object]] = Field(default_factory=list)
    debug_notes: list[str] = Field(default_factory=list)
