from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field

from crisis_room.engine.actions import ActionPackage
from crisis_room.llm.contracts import LLMClient
from crisis_room.state.signals import Signal, SignalDelivery
from crisis_room.state.timelines import TimelineEntry
from crisis_room.state.world import EntityState, WorldStateV2


class AgentInput(BaseModel):
    entity_id: str
    turn_number: int
    inbox: list[SignalDelivery] = Field(default_factory=list)
    public_timeline_delta: list[TimelineEntry] = Field(default_factory=list)
    world_excerpt: dict[str, str | int | float | bool] = Field(default_factory=dict)


class AgentOutput(BaseModel):
    entity_id: str
    perception_summary: str = ""
    internal_debate: list[str] = Field(default_factory=list)
    action_package: ActionPackage | None = None
    public_timeline_delta: list[TimelineEntry] = Field(default_factory=list)
    emitted_signals: list[Signal] = Field(default_factory=list)
    raw_llm_outputs: list[dict[str, object]] = Field(default_factory=list)
    debug_notes: list[str] = Field(default_factory=list)


class EntityAgent(Protocol):
    entity_id: str

    def run_turn(
        self,
        entity_state: EntityState,
        world_state: WorldStateV2,
        llm_client: LLMClient,
    ) -> AgentOutput:
        """Produce one entity's turn output without mutating authoritative state."""


class StaticEntityAgent:
    """Simple Phase 1 fake agent used to exercise orchestration without live LLMs."""

    def __init__(self, entity_id: str, output: AgentOutput | None = None) -> None:
        self.entity_id = entity_id
        self._output = output

    def run_turn(
        self,
        entity_state: EntityState,
        world_state: WorldStateV2,
        llm_client: LLMClient,
    ) -> AgentOutput:
        if self._output is not None:
            return self._output
        return AgentOutput(
            entity_id=entity_state.entity_id,
            perception_summary=f"{entity_state.name} has {len(entity_state.inbox)} inbox item(s).",
            internal_debate=[
                narrative.current_argument or narrative.preferred_strategy
                for narrative in entity_state.internal_narratives
            ],
            debug_notes=[f"fake agent ran on turn {world_state.turn_number}"],
        )
