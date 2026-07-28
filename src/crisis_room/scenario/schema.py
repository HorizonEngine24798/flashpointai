from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from crisis_room.engine.actions import ActionDefinition, ScenarioCapability
from crisis_room.scenario.endings import ScenarioEndingDefinition
from crisis_room.scenario.events import (
    ScenarioEventDefinition,
    ScenarioEventSettings,
)
from crisis_room.scenario.pressure import HiddenObligation, PressureRule
from crisis_room.state.advisors import AdvisorCouncilState
from crisis_room.state.beliefs import BeliefState, InternalNarrative
from crisis_room.state.timelines import TimelineEntry
from crisis_room.state.world import EntityState, EntityType, WorldStateV2


class ScenarioMetadata(BaseModel):
    title: str
    historical_period: str = ""
    description: str = ""
    designer_notes: list[str] = Field(default_factory=list)


class ScenarioEntitySpec(BaseModel):
    entity_id: str
    name: str
    entity_type: EntityType
    role: str
    public_goals: list[str] = Field(default_factory=list)
    private_goals: list[str] = Field(default_factory=list)
    internal_narratives: list[InternalNarrative] = Field(default_factory=list)
    initial_beliefs: BeliefState = Field(default_factory=BeliefState)
    resources: dict[str, int] = Field(default_factory=dict)
    doctrine: str = ""

    def to_entity_state(self) -> EntityState:
        return EntityState(
            entity_id=self.entity_id,
            name=self.name,
            entity_type=self.entity_type,
            role=self.role,
            public_goals=self.public_goals,
            private_goals=self.private_goals,
            internal_narratives=self.internal_narratives,
            beliefs=self.initial_beliefs,
            resources=self.resources,
            doctrine=self.doctrine,
        )


class Scenario(BaseModel):
    scenario_id: str
    metadata: ScenarioMetadata
    intro_text: str
    player_entity_id: str
    entities: list[ScenarioEntitySpec]
    action_catalog: list[ActionDefinition] = Field(default_factory=list)
    capabilities: list[ScenarioCapability] = Field(default_factory=list)
    scenario_events: list[ScenarioEventDefinition] = Field(default_factory=list)
    scenario_endings: list[ScenarioEndingDefinition] = Field(default_factory=list)
    pressure_rules: list[PressureRule] = Field(default_factory=list)
    hidden_obligations: list[HiddenObligation] = Field(default_factory=list)
    event_settings: ScenarioEventSettings = Field(default_factory=ScenarioEventSettings)
    initial_public_timeline: list[TimelineEntry] = Field(default_factory=list)
    initial_omniscient_timeline: list[TimelineEntry] = Field(default_factory=list)
    initial_entity_timelines: dict[str, list[TimelineEntry]] = Field(default_factory=dict)
    initial_truth_metrics: dict[str, float] = Field(default_factory=dict)
    initial_public_metrics: dict[str, float] = Field(default_factory=dict)
    initial_hidden_clocks: dict[str, float] = Field(default_factory=dict)
    initial_advisor_councils: dict[str, AdvisorCouncilState] = Field(default_factory=dict)
    def create_initial_world(self, rng_seed: int = 0) -> WorldStateV2:
        world = WorldStateV2(
            scenario_id=self.scenario_id,
            rng_seed=rng_seed,
            truth_metrics=self.initial_truth_metrics,
            public_metrics=self.initial_public_metrics,
            hidden_clocks=self.initial_hidden_clocks,
            advisor_councils={
                entity_id: council.model_copy(deep=True)
                for entity_id, council in self.initial_advisor_councils.items()
            },
            actors={entity.entity_id: entity.to_entity_state() for entity in self.entities},
            metadata={"player_entity_id": self.player_entity_id},
        )
        for index, entry in enumerate(self.initial_public_timeline):
            world.public_timeline.append(
                _initial_entry(entry, self.scenario_id, "public", index)
            )
        for index, entry in enumerate(self.initial_omniscient_timeline):
            world.omniscient_timeline.append(
                _initial_entry(entry, self.scenario_id, "omniscient", index)
            )
        for entity in self.entities:
            timeline = world.ensure_entity_timeline(entity.entity_id)
            for index, entry in enumerate(
                self.initial_entity_timelines.get(entity.entity_id, [])
            ):
                timeline.append(
                    _initial_entry(entry, self.scenario_id, entity.entity_id, index)
                )
        return world


def _initial_entry(
    entry: TimelineEntry,
    scenario_id: str,
    scope: str,
    index: int,
) -> TimelineEntry:
    return entry.model_copy(
        deep=True,
        update={
            "entry_id": f"seed_{scenario_id}_{scope}_{index}",
            "created_at": datetime.fromtimestamp(index, tz=timezone.utc),
        },
    )
