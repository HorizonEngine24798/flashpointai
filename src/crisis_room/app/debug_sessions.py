from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re

from pydantic import BaseModel, Field

from crisis_room.app.planning import PlayerPlanPreview
from crisis_room.app.turn_orchestrator import TurnDebugTranscript
from crisis_room.llm.contracts import LLMCallRecord
from crisis_room.llm.task_contracts import AdvisorCouncilResponse
from crisis_room.state.world import WorldStateV2


class DialogueDebugRecord(BaseModel):
    turn: int
    player_message: str
    response: AdvisorCouncilResponse
    llm_calls: list[LLMCallRecord] = Field(default_factory=list)


class PlanPreviewDebugRecord(BaseModel):
    turn: int
    player_intent: str
    preview: PlayerPlanPreview
    rendered_text: str = ""
    llm_calls: list[LLMCallRecord] = Field(default_factory=list)


class LLMTaskDebugRecord(BaseModel):
    turn: int
    label: str
    rendered_text: str = ""
    llm_calls: list[LLMCallRecord] = Field(default_factory=list)


class DebugSessionRecord(BaseModel):
    session_id: str
    scenario_id: str
    player_entity_id: str
    started_at: datetime
    updated_at: datetime
    world_state: WorldStateV2
    dialogue_records: list[DialogueDebugRecord] = Field(default_factory=list)
    plan_previews: list[PlanPreviewDebugRecord] = Field(default_factory=list)
    llm_task_records: list[LLMTaskDebugRecord] = Field(default_factory=list)
    turn_transcripts: list[TurnDebugTranscript] = Field(default_factory=list)
    rendered_log: list[str] = Field(default_factory=list)


class DebugSessionRecorder:
    """Persist playable debug sessions as JSON artifacts."""

    def __init__(
        self,
        *,
        world_state: WorldStateV2,
        player_entity_id: str,
        output_dir: str | Path = "output/debug_sessions",
    ) -> None:
        now = datetime.now(timezone.utc)
        self.output_dir = Path(output_dir)
        self.record = DebugSessionRecord(
            session_id=f"{_slug(world_state.scenario_id)}_{now.strftime('%Y%m%d_%H%M%S')}",
            scenario_id=world_state.scenario_id,
            player_entity_id=player_entity_id,
            started_at=now,
            updated_at=now,
            world_state=world_state.model_copy(deep=True),
        )

    @property
    def path(self) -> Path:
        return self.output_dir / f"{self.record.session_id}.json"

    def append_dialogue(
        self,
        *,
        turn: int,
        player_message: str,
        response: AdvisorCouncilResponse,
        llm_calls: list[LLMCallRecord],
    ) -> None:
        self.record.dialogue_records.append(
            DialogueDebugRecord(
                turn=turn,
                player_message=player_message,
                response=response,
                llm_calls=[call.model_copy(deep=True) for call in llm_calls],
            )
        )
        self.record.rendered_log.append(f"[turn {turn} dialogue] {player_message}")
        self._touch()

    def append_plan_preview(
        self,
        *,
        turn: int,
        player_intent: str,
        preview: PlayerPlanPreview,
        rendered_text: str,
        llm_calls: list[LLMCallRecord],
    ) -> None:
        self.record.plan_previews.append(
            PlanPreviewDebugRecord(
                turn=turn,
                player_intent=player_intent,
                preview=preview.model_copy(deep=True),
                rendered_text=rendered_text,
                llm_calls=[call.model_copy(deep=True) for call in llm_calls],
            )
        )
        if rendered_text:
            self.record.rendered_log.append(rendered_text)
        self._touch()

    def append_llm_task(
        self,
        *,
        turn: int,
        label: str,
        llm_calls: list[LLMCallRecord],
        rendered_text: str = "",
    ) -> None:
        self.record.llm_task_records.append(
            LLMTaskDebugRecord(
                turn=turn,
                label=label,
                rendered_text=rendered_text,
                llm_calls=[call.model_copy(deep=True) for call in llm_calls],
            )
        )
        if rendered_text:
            self.record.rendered_log.append(rendered_text)
        self._touch()

    def append_turn(self, transcript: TurnDebugTranscript, world_state: WorldStateV2) -> None:
        self.record.turn_transcripts.append(transcript.model_copy(deep=True))
        self.record.world_state = world_state.model_copy(deep=True)
        self.record.rendered_log.append(transcript.rendered_text)
        self._touch()

    def update_world_state(
        self,
        world_state: WorldStateV2,
        *,
        rendered_log_entry: str = "",
    ) -> None:
        self.record.world_state = world_state.model_copy(deep=True)
        if rendered_log_entry:
            self.record.rendered_log.append(rendered_log_entry)
        self._touch()

    def save(self) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.path.write_text(self.record.model_dump_json(indent=2), encoding="utf-8")
        return self.path

    def _touch(self) -> None:
        self.record.updated_at = datetime.now(timezone.utc)


def load_debug_session(path: str | Path) -> DebugSessionRecord:
    return DebugSessionRecord.model_validate_json(Path(path).read_text(encoding="utf-8"))


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return cleaned.strip("_") or "debug_session"
