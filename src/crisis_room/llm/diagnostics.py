from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class LlamaCppError(RuntimeError):
    """Base error for local llama.cpp inference failures."""


class LlamaCppStartupError(LlamaCppError):
    """The managed llama-server process could not become ready."""


class LlamaCppTransportError(LlamaCppError):
    """The chat-completions HTTP request failed."""


class LlamaCppJSONError(LlamaCppError):
    """The model response did not satisfy the JSON contract."""


class DiagnosticArtifact(BaseModel):
    schema_version: str = "llm_diagnostic_v1"
    label: str
    backend: str = "llama_cpp_server"
    model: str = ""
    attempt: int
    error_type: str
    error_message: str
    raw_response: Any | None = None
    fitted_messages: list[dict[str, Any]] = Field(default_factory=list)
    estimated_input_tokens: int | None = None
    max_input_tokens: int | None = None
    max_new_tokens: int | None = None
    was_truncated: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def write_diagnostic_artifact(
    artifact: DiagnosticArtifact,
    output_dir: str | Path = "output/diagnostics/ai_invalid_json",
) -> Path:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    safe_label = "".join(
        char if char.isalnum() or char in {"-", "_"} else "_"
        for char in artifact.label
    )[:80] or "llm_call"
    path = directory / f"{safe_label}_{artifact.attempt}_{uuid4().hex[:8]}.json"
    path.write_text(
        json.dumps(artifact.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return path
