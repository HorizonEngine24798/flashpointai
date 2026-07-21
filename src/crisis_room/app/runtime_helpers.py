from __future__ import annotations

from crisis_room.llm.contracts import LLMCallRecord, LLMClient
from crisis_room.llm.diagnostics import LlamaCppError


ADVISOR_RETRY_TEXT = (
    "The room talks over itself; ask a narrower question.\n"
    "The turn has not advanced."
)


def format_runtime_error(context: str, exc: Exception) -> str:
    if not isinstance(exc, LlamaCppError):
        return f"{context} failed: {type(exc).__name__}: {exc}"
    lines = [
        f"{context} failed.",
        f"Live LLM error: {type(exc).__name__}",
    ]
    details = str(exc).strip()
    if details:
        lines.append("Details:")
        lines.extend(f"  {part.strip()}" for part in details.split("; ") if part.strip())
    return "\n".join(lines)


def format_advisor_retry_error(exc: Exception, *, debug_mode: bool = False) -> str:
    if not debug_mode:
        return ADVISOR_RETRY_TEXT
    return f"{ADVISOR_RETRY_TEXT}\n\n{format_runtime_error('Advisor dialogue', exc)}"


def llm_call_count(llm_client: LLMClient) -> int:
    calls = getattr(llm_client, "calls", [])
    return len(calls) if isinstance(calls, list) else 0


def llm_call_records(
    llm_client: LLMClient,
    *,
    start_index: int = 0,
) -> list[LLMCallRecord]:
    calls = getattr(llm_client, "calls", [])
    if not isinstance(calls, list):
        return []
    records: list[LLMCallRecord] = []
    for call in calls[start_index:]:
        if isinstance(call, LLMCallRecord):
            records.append(call.model_copy(deep=True))
        elif isinstance(call, dict):
            records.append(LLMCallRecord.model_validate(call))
    return records
