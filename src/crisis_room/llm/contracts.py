from __future__ import annotations

from enum import Enum
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, Field


class ChatRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class LLMMessage(BaseModel):
    role: ChatRole
    content: str


class LLMRequest(BaseModel):
    label: str
    messages: list[LLMMessage]
    max_tokens: int = Field(default=1024, ge=1)
    response_schema_name: str | None = None
    metadata: dict[str, str | int | float | bool] = Field(default_factory=dict)


class LLMCallRecord(BaseModel):
    request: LLMRequest
    raw_response: Any
    parsed_response: Any | None = None
    validation_error: str | None = None


ResponseModelT = TypeVar("ResponseModelT", bound=BaseModel)


class LLMClient(Protocol):
    def complete_json(
        self,
        request: LLMRequest,
        response_model: type[ResponseModelT],
    ) -> ResponseModelT:
        """Return a typed JSON response for an LLM task."""


class FakeLLMClient:
    """Deterministic test double for typed LLM calls."""

    def __init__(self, responses: dict[str, Any] | list[Any] | None = None) -> None:
        self._responses = responses or {}
        self.calls: list[LLMCallRecord] = []
        self._cursor = 0

    def complete_json(
        self,
        request: LLMRequest,
        response_model: type[ResponseModelT],
    ) -> ResponseModelT:
        raw = self._next_response(request.label)
        record = LLMCallRecord(request=request, raw_response=raw)
        try:
            parsed = raw if isinstance(raw, response_model) else response_model.model_validate(raw)
        except Exception as exc:
            record.validation_error = str(exc)
            self.calls.append(record)
            raise
        record.parsed_response = parsed.model_dump(mode="json")
        self.calls.append(record)
        return parsed

    def _next_response(self, label: str) -> Any:
        if isinstance(self._responses, list):
            if self._cursor >= len(self._responses):
                return {}
            raw = self._responses[self._cursor]
            self._cursor += 1
            return raw
        return self._responses.get(label, {})
