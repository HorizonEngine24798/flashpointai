from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


class TimelineScope(str, Enum):
    OMNISCIENT = "omniscient"
    PUBLIC = "public"
    ENTITY_LOCAL = "entity_local"


class TimelineEntry(BaseModel):
    entry_id: str = Field(default_factory=lambda: str(uuid4()))
    turn: int = Field(ge=0)
    scope: TimelineScope
    title: str
    summary: str
    visible_to: list[str] = Field(default_factory=list)
    source: str = "system"
    signal_ids: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, str | int | float | bool] = Field(default_factory=dict)

    def public_copy(self) -> TimelineEntry:
        """Return a public-safe copy without hidden visibility metadata."""

        return TimelineEntry(
            entry_id=f"public_{self.entry_id}",
            turn=self.turn,
            scope=TimelineScope.PUBLIC,
            title=self.title,
            summary=self.summary,
            source=self.source,
            signal_ids=list(self.signal_ids),
            tags=[tag for tag in self.tags if tag not in {"secret", "covert", "private"}],
            created_at=self.created_at,
            metadata={
                key: value
                for key, value in self.metadata.items()
                if key.startswith("public_") or key in {"rumor", "leaked", "distorted"}
            },
        )


class Timeline(BaseModel):
    scope: TimelineScope
    owner_entity_id: str | None = None
    entries: list[TimelineEntry] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_owner_for_entity_timeline(self) -> Timeline:
        if self.scope == TimelineScope.ENTITY_LOCAL and not self.owner_entity_id:
            raise ValueError("entity-local timelines require owner_entity_id")
        return self

    def append(self, entry: TimelineEntry) -> None:
        if entry.scope != self.scope:
            raise ValueError(f"cannot append {entry.scope} entry to {self.scope} timeline")
        if self.owner_entity_id and self.owner_entity_id not in entry.visible_to:
            entry.visible_to.append(self.owner_entity_id)
        self.entries.append(entry)

    def latest(self, count: int = 5) -> list[TimelineEntry]:
        return self.entries[-count:]
