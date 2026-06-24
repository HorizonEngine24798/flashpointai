from __future__ import annotations

import re

from crisis_room.llm.task_contracts import SignalCandidate
from crisis_room.state.signals import Signal, SignalChannel, SignalVisibility


def signal_from_candidate(
    candidate: SignalCandidate,
    *,
    source_entity_id: str,
    turn_number: int,
    suffix: str,
    known_entity_ids: set[str] | None = None,
    metadata: dict[str, str | int | float | bool] | None = None,
) -> Signal:
    is_public = (
        candidate.visibility == SignalVisibility.PUBLIC
        or candidate.channel in {SignalChannel.PUBLIC, SignalChannel.MEDIA}
    )
    target_ids = [] if is_public else list(candidate.target_entity_ids)
    if known_entity_ids is not None:
        target_ids = [target_id for target_id in target_ids if target_id in known_entity_ids]
    return Signal(
        signal_id=f"sig_{turn_number}_{_safe_id(source_entity_id)}_{_safe_id(suffix)}",
        source_entity_id=source_entity_id,
        recipient_entity_ids=target_ids,
        channel=candidate.channel,
        payload_type=candidate.payload_type,
        content=candidate.content,
        emitted_turn=turn_number,
        intended_arrival_turn=turn_number,
        visibility=SignalVisibility.PUBLIC if is_public else candidate.visibility,
        reliability=candidate.reliability,
        leak_risk=candidate.leak_risk,
        distortion_risk=candidate.distortion_risk,
        urgency=candidate.urgency,
        classification=candidate.classification,
        metadata=metadata or {},
    )


def _safe_id(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return cleaned.strip("_") or "signal"
