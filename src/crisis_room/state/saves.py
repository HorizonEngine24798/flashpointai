from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from pydantic import BaseModel, Field

from crisis_room.app.planning import PlayerPlanPreview
from crisis_room.state.world import WorldStateV2


class PendingPlayablePlan(BaseModel):
    turn_number: int
    player_entity_id: str
    world_fingerprint: str
    preview: PlayerPlanPreview


class PlayableSaveRecord(BaseModel):
    schema_version: str = "playable_save_v1"
    save_id: str
    scenario_id: str
    player_entity_id: str
    saved_at: datetime
    world_state: WorldStateV2
    pending_plan: PendingPlayablePlan | None = None
    metadata: dict[str, str | int | float | bool] = Field(default_factory=dict)


def build_playable_save_record(
    *,
    world_state: WorldStateV2,
    player_entity_id: str,
    pending_plan: PlayerPlanPreview | None = None,
    save_id: str | None = None,
) -> PlayableSaveRecord:
    saved_at = datetime.now(timezone.utc)
    fingerprint = world_state_fingerprint(world_state)
    return PlayableSaveRecord(
        save_id=save_id or _default_save_id(world_state, saved_at),
        scenario_id=world_state.scenario_id,
        player_entity_id=player_entity_id,
        saved_at=saved_at,
        world_state=world_state.model_copy(deep=True),
        pending_plan=_build_pending_plan(
            pending_plan,
            world_state=world_state,
            player_entity_id=player_entity_id,
            world_fingerprint=fingerprint,
        ),
    )


def save_playable_session(
    *,
    world_state: WorldStateV2,
    player_entity_id: str,
    output_dir: str | Path = "saves",
    pending_plan: PlayerPlanPreview | None = None,
    save_id: str | None = None,
) -> Path:
    record = build_playable_save_record(
        world_state=world_state,
        player_entity_id=player_entity_id,
        pending_plan=pending_plan,
        save_id=save_id,
    )
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{record.save_id}.json"
    path.write_text(record.model_dump_json(indent=2), encoding="utf-8")
    return path


def load_playable_session(path: str | Path) -> PlayableSaveRecord:
    return PlayableSaveRecord.model_validate_json(Path(path).read_text(encoding="utf-8"))


def restore_pending_plan(record: PlayableSaveRecord) -> PlayerPlanPreview | None:
    pending = record.pending_plan
    if pending is None:
        return None
    if not pending_plan_matches_world(
        pending.preview,
        record.world_state,
        record.player_entity_id,
        expected_fingerprint=pending.world_fingerprint,
    ):
        return None
    return pending.preview.model_copy(deep=True)


def pending_plan_matches_world(
    preview: PlayerPlanPreview,
    world_state: WorldStateV2,
    player_entity_id: str,
    *,
    expected_fingerprint: str | None = None,
) -> bool:
    if preview.player_entity_id != player_entity_id:
        return False
    if preview.turn_number != world_state.turn_number:
        return False
    if not preview.is_committable:
        return False
    if expected_fingerprint is None:
        return True
    return world_state_fingerprint(world_state) == expected_fingerprint


def world_state_fingerprint(world_state: WorldStateV2) -> str:
    payload = world_state.model_dump(mode="json")
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _build_pending_plan(
    pending_plan: PlayerPlanPreview | None,
    *,
    world_state: WorldStateV2,
    player_entity_id: str,
    world_fingerprint: str,
) -> PendingPlayablePlan | None:
    if pending_plan is None:
        return None
    if not pending_plan_matches_world(
        pending_plan,
        world_state,
        player_entity_id,
        expected_fingerprint=world_fingerprint,
    ):
        return None
    return PendingPlayablePlan(
        turn_number=pending_plan.turn_number,
        player_entity_id=player_entity_id,
        world_fingerprint=world_fingerprint,
        preview=pending_plan.model_copy(deep=True),
    )


def _default_save_id(world_state: WorldStateV2, saved_at: datetime) -> str:
    scenario = _slug(world_state.scenario_id)
    stamp = saved_at.strftime("%Y%m%d_%H%M%S_%f")
    return f"{scenario}_turn_{world_state.turn_number}_{stamp}"


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return cleaned.strip("_") or "playable_save"
