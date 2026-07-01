from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from crisis_room.engine.actions import ActionPackage
from crisis_room.state.advisors import AdvisorCouncilState, AdvisorCouncilUpdate
from crisis_room.state.backchannels import BackchannelThread, BackchannelThreadUpdate
from crisis_room.state.beliefs import BeliefState, InternalNarrative
from crisis_room.state.endings import EndingOfferRecord
from crisis_room.state.events import ScenarioEventChoiceRecord, ScenarioEventRecord
from crisis_room.state.signals import Signal, SignalDelivery
from crisis_room.state.timelines import Timeline, TimelineEntry, TimelineScope


class EntityType(str, Enum):
    PLAYER_FACTION = "player_faction"
    ALLIED_FACTION = "allied_faction"
    OPPOSING_FACTION = "opposing_faction"
    INTERNATIONAL_COMMUNITY = "international_community"
    DIALOGUE_ENGINE = "dialogue_engine"
    GAMEMASTER = "gamemaster"
    EVENT_CREATOR = "event_creator"
    INFO_CHANNEL = "info_channel"


class EntityState(BaseModel):
    entity_id: str
    name: str
    entity_type: EntityType
    role: str
    public_goals: list[str] = Field(default_factory=list)
    private_goals: list[str] = Field(default_factory=list)
    internal_narratives: list[InternalNarrative] = Field(default_factory=list)
    memory_summary: str = ""
    beliefs: BeliefState = Field(default_factory=BeliefState)
    inbox: list[SignalDelivery] = Field(default_factory=list)
    outbox: list[Signal] = Field(default_factory=list)
    doctrine: str = ""
    known_commitments: list[str] = Field(default_factory=list)
    unresolved_threads: list[str] = Field(default_factory=list)
    confidence_map: dict[str, float] = Field(default_factory=dict)
    resources: dict[str, int] = Field(default_factory=dict)
    metadata: dict[str, str | int | float | bool] = Field(default_factory=dict)


class WorldStateV2(BaseModel):
    schema_version: str = "world_state_v2"
    scenario_id: str
    turn_number: int = Field(default=1, ge=0)
    time_label: str = ""
    rng_seed: int = 0
    truth_metrics: dict[str, float] = Field(default_factory=dict)
    public_metrics: dict[str, float] = Field(default_factory=dict)
    hidden_clocks: dict[str, float] = Field(default_factory=dict)
    actors: dict[str, EntityState] = Field(default_factory=dict)
    relationships: dict[str, dict[str, float]] = Field(default_factory=dict)
    advisor_councils: dict[str, AdvisorCouncilState] = Field(default_factory=dict)
    advisor_update_history: list[AdvisorCouncilUpdate] = Field(default_factory=list)
    backchannel_threads: dict[str, BackchannelThread] = Field(default_factory=dict)
    backchannel_update_history: list[BackchannelThreadUpdate] = Field(default_factory=list)
    event_history: list[ScenarioEventRecord] = Field(default_factory=list)
    pending_event_choices: list[ScenarioEventChoiceRecord] = Field(default_factory=list)
    ending_offers: list[EndingOfferRecord] = Field(default_factory=list)
    accepted_ending_id: str = ""
    accepted_ending_offer_id: str = ""
    accepted_ending_turn: int | None = Field(default=None, ge=0)
    final_summary: str = ""
    ending_reoffer_after_turns: dict[str, int] = Field(default_factory=dict)
    active_commitments: list[str] = Field(default_factory=list)
    pending_actions: list[ActionPackage] = Field(default_factory=list)
    pending_signals: list[Signal] = Field(default_factory=list)
    omniscient_timeline: Timeline = Field(
        default_factory=lambda: Timeline(scope=TimelineScope.OMNISCIENT)
    )
    public_timeline: Timeline = Field(
        default_factory=lambda: Timeline(scope=TimelineScope.PUBLIC)
    )
    entity_timelines: dict[str, Timeline] = Field(default_factory=dict)
    metadata: dict[str, str | int | float | bool] = Field(default_factory=dict)

    def require_entity(self, entity_id: str) -> EntityState:
        try:
            return self.actors[entity_id]
        except KeyError as exc:
            raise KeyError(f"unknown entity: {entity_id}") from exc

    def ensure_entity_timeline(self, entity_id: str) -> Timeline:
        if entity_id not in self.entity_timelines:
            self.entity_timelines[entity_id] = Timeline(
                scope=TimelineScope.ENTITY_LOCAL,
                owner_entity_id=entity_id,
            )
        return self.entity_timelines[entity_id]

    def append_omniscient(self, title: str, summary: str, **metadata: object) -> TimelineEntry:
        entry = TimelineEntry(
            turn=self.turn_number,
            scope=TimelineScope.OMNISCIENT,
            title=title,
            summary=summary,
            source="gamemaster",
            metadata=_timeline_metadata(metadata),
        )
        self.omniscient_timeline.append(entry)
        return entry

    def append_public(self, title: str, summary: str, **metadata: object) -> TimelineEntry:
        entry = TimelineEntry(
            turn=self.turn_number,
            scope=TimelineScope.PUBLIC,
            title=title,
            summary=summary,
            source="public_record",
            metadata=_timeline_metadata(metadata),
        )
        self.public_timeline.append(entry)
        return entry

    def deliver_to_entity(self, delivery: SignalDelivery) -> None:
        entity = self.require_entity(delivery.recipient_entity_id)
        entity.inbox.append(delivery)
        timeline = self.ensure_entity_timeline(delivery.recipient_entity_id)
        timeline.append(
            TimelineEntry(
                turn=delivery.arrived_turn,
                scope=TimelineScope.ENTITY_LOCAL,
                title=f"Received {delivery.payload_type.value}",
                summary=delivery.observed_content,
                visible_to=[delivery.recipient_entity_id],
                source=delivery.source_entity_id,
                signal_ids=[delivery.signal_id],
                tags=["inbox", delivery.channel.value],
                metadata={
                    "distorted": delivery.distortion_applied,
                    "contradictory": delivery.contradiction_applied,
                    "leaked": delivery.leak_applied,
                    "observed_reliability": delivery.observed_reliability,
                },
            )
        )

    def append_entity_timeline(
        self,
        entity_id: str,
        title: str,
        summary: str,
        *,
        source: str = "system",
        signal_ids: list[str] | None = None,
        tags: list[str] | None = None,
        **metadata: object,
    ) -> TimelineEntry:
        timeline = self.ensure_entity_timeline(entity_id)
        entry = TimelineEntry(
            turn=self.turn_number,
            scope=TimelineScope.ENTITY_LOCAL,
            title=title,
            summary=summary,
            visible_to=[entity_id],
            source=source,
            signal_ids=signal_ids or [],
            tags=tags or [],
            metadata=_timeline_metadata(metadata),
        )
        timeline.append(entry)
        return entry


WorldState = WorldStateV2


def _timeline_metadata(values: dict[str, object]) -> dict[str, str | int | float | bool]:
    return {
        key: value
        for key, value in values.items()
        if isinstance(value, str | int | float | bool)
    }
