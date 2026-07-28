from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from crisis_room.config.settings import LlamaCppSettings
from crisis_room.llm.contracts import (
    ChatRole,
    LLMCallRecord,
    LLMMessage,
    LLMRequest,
    ResponseModelT,
)
from crisis_room.llm.diagnostics import (
    DiagnosticArtifact,
    LlamaCppJSONError,
    LlamaCppTransportError,
    write_diagnostic_artifact,
)
from crisis_room.llm.prompt_fitting import PromptFitResult, fit_messages_to_budget
from crisis_room.llm.prompts import JSON_RETRY_INSTRUCTION

class LlamaCppServerClient:
    """Client for an already-running OpenAI-compatible chat API."""

    def __init__(
        self,
        settings: LlamaCppSettings | None = None,
        *,
        http_client: httpx.Client | None = None,
        diagnostics_dir: str | Path | None = None,
        campaign_seed: int | None = None,
        response_cache_dir: str | Path | None = None,
    ) -> None:
        self.settings = settings or LlamaCppSettings()
        headers = (
            {"Authorization": f"Bearer {self.settings.api_key}"}
            if self.settings.api_key
            else None
        )
        self._http_client = http_client or httpx.Client(
            headers=headers,
            trust_env=False,
        )
        self._owns_http_client = http_client is None
        self.diagnostics_dir = Path(
            diagnostics_dir or self.settings.diagnostics_dir
        )
        self.campaign_seed = campaign_seed
        self.response_cache_dir = (
            Path(response_cache_dir) if response_cache_dir is not None else None
        )
        self.calls: list[LLMCallRecord] = []

    def complete_json(
        self,
        request: LLMRequest,
        response_model: type[ResponseModelT],
    ) -> ResponseModelT:
        attempts = self.settings.json_retries + 1
        last_error: Exception | None = None
        last_artifact: Path | None = None
        first_payload: dict[str, Any] | None = None

        for attempt in range(1, attempts + 1):
            attempt_request = _request_for_attempt(request, attempt)
            fit = fit_messages_to_budget(attempt_request.messages, self.settings)
            payload = self.build_payload(attempt_request, response_model, fit)
            first_payload = first_payload or payload
            record = LLMCallRecord(request=attempt_request, raw_response=None)

            cached = self._cached_response(payload, response_model)
            if cached is not None:
                record.raw_response = {"response_cache_hit": True}
                record.parsed_response = cached.model_dump(mode="json")
                self.calls.append(record)
                return cached

            try:
                raw_response = self._post_payload(
                    payload,
                    request_label=attempt_request.label,
                )
                record.raw_response = raw_response
                content = extract_message_content(raw_response).strip()
                parsed = parse_json_object(content)
                response = response_model.model_validate(parsed)
                record.parsed_response = response.model_dump(mode="json")
                self.calls.append(record)
                self._cache_response(payload, response)
                if first_payload is not payload:
                    self._cache_response(first_payload, response)
                return response
            except (json.JSONDecodeError, LlamaCppJSONError, ValidationError) as exc:
                last_error = exc
                record.validation_error = str(exc)
                self.calls.append(record)
                last_artifact = self._write_invalid_json_artifact(
                    request=attempt_request,
                    fit=fit,
                    attempt=attempt,
                    raw_response=record.raw_response,
                    error=exc,
                )
                continue
            except LlamaCppTransportError as exc:
                record.validation_error = str(exc)
                self.calls.append(record)
                raise
            except httpx.HTTPError as exc:
                record.validation_error = str(exc)
                self.calls.append(record)
                raise LlamaCppTransportError(
                    f"llama.cpp transport failed; task_label={attempt_request.label}; "
                    f"schema={attempt_request.response_schema_name or response_model.__name__}; "
                    f"attempt={attempt}; url={self.settings.chat_completions_url}; "
                    f"error={type(exc).__name__}: {exc}"
                ) from exc

        schema_name = request.response_schema_name or response_model.__name__
        raise LlamaCppJSONError(
            "llama.cpp response did not satisfy JSON contract; "
            f"task_label={request.label}; schema={schema_name}; "
            f"attempts={attempts}; diagnostic_artifact={last_artifact}; "
            f"last_error={type(last_error).__name__ if last_error else '(none)'}: "
            f"{last_error}"
        )

    def build_payload(
        self,
        request: LLMRequest,
        response_model: type[BaseModel],
        fit: PromptFitResult | None = None,
    ) -> dict[str, Any]:
        fit = fit or fit_messages_to_budget(request.messages, self.settings)
        schema = response_model.model_json_schema()
        payload: dict[str, Any] = {
            "model": self.settings.server_model,
            "messages": [
                {"role": message.role.value, "content": message.content}
                for message in fit.messages
            ],
            "max_tokens": min(request.max_tokens, self.settings.max_new_tokens),
            "temperature": self.settings.temperature,
            "top_p": self.settings.top_p,
            "response_format": {"type": "json_object"},
        }
        if self.campaign_seed is not None:
            payload["seed"] = _derived_seed(
                self.campaign_seed,
                request,
                fit.messages,
                response_model,
            )
            if self.settings.cache_prompt is not None:
                payload["cache_prompt"] = self.settings.cache_prompt
        if request.response_schema_name:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": request.response_schema_name,
                    "schema": schema,
                },
            }
            payload["json_schema"] = schema
        return payload

    def _cached_response(
        self,
        payload: dict[str, Any],
        response_model: type[ResponseModelT],
    ) -> ResponseModelT | None:
        path = self._cache_path(payload)
        if path is None or not path.is_file():
            return None
        try:
            return response_model.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _cache_response(self, payload: dict[str, Any], response: BaseModel) -> None:
        path = self._cache_path(payload)
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(response.model_dump_json(indent=2), encoding="utf-8")
            temporary.replace(path)
        except OSError:
            return

    def _cache_path(self, payload: dict[str, Any]) -> Path | None:
        if self.response_cache_dir is None:
            return None
        material = {
            "backend": self.settings.backend,
            "base_url": self.settings.base_url,
            "server_model": self.settings.server_model,
            "payload": payload,
        }
        digest = hashlib.sha256(
            json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return self.response_cache_dir / f"{digest}.json"

    def close(self) -> None:
        if self._owns_http_client:
            self._http_client.close()

    def __enter__(self) -> LlamaCppServerClient:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def _post_payload(
        self,
        payload: dict[str, Any],
        *,
        request_label: str,
    ) -> dict[str, Any]:
        response = self._http_client.post(
            self.settings.chat_completions_url,
            json=payload,
            timeout=self.settings.request_timeout_seconds,
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            body_preview = response.text[:500]
            raise LlamaCppTransportError(
                f"llama.cpp transport failed; task_label={request_label}; "
                f"url={self.settings.chat_completions_url}; "
                f"status={response.status_code}; body_preview="
                f"{body_preview}"
            ) from exc
        try:
            raw = response.json()
        except ValueError as exc:
            raise LlamaCppTransportError(
                f"llama.cpp transport failed; task_label={request_label}; "
                f"url={self.settings.chat_completions_url}; "
                f"chat response was not valid JSON HTTP payload: {exc}"
            ) from exc
        if not isinstance(raw, dict):
            raise LlamaCppTransportError(
                f"llama.cpp transport failed; task_label={request_label}; "
                f"url={self.settings.chat_completions_url}; "
                "chat response HTTP payload was not an object"
            )
        return raw

    def _write_invalid_json_artifact(
        self,
        *,
        request: LLMRequest,
        fit: PromptFitResult,
        attempt: int,
        raw_response: Any,
        error: Exception,
    ) -> Path:
        artifact = DiagnosticArtifact(
            label=request.label,
            model=self.settings.server_model,
            attempt=attempt,
            error_type=type(error).__name__,
            error_message=str(error),
            raw_response=raw_response,
            fitted_messages=[message.model_dump(mode="json") for message in fit.messages],
            estimated_input_tokens=fit.estimated_input_tokens,
            max_input_tokens=self.settings.max_input_tokens,
            max_new_tokens=min(request.max_tokens, self.settings.max_new_tokens),
            was_truncated=fit.was_truncated,
            metadata={
                "response_schema_name": request.response_schema_name or "",
                "request_metadata": request.metadata,
                "truncation_notes": fit.truncation_notes,
            },
        )
        return write_diagnostic_artifact(artifact, self.diagnostics_dir)


def extract_message_content(raw_response: dict[str, Any]) -> str:
    choices = raw_response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LlamaCppJSONError("chat response missing choices")
    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise LlamaCppJSONError("chat response choice was not an object")
    message = first_choice.get("message")
    if not isinstance(message, dict):
        raise LlamaCppJSONError("chat response missing message")

    content = _stringify_content(message.get("content"))
    if content.strip():
        return content

    reasoning = _stringify_content(message.get("reasoning_content"))
    if reasoning.strip():
        return reasoning
    raise LlamaCppJSONError("chat response message content was empty")


def parse_json_object(content: str) -> dict[str, Any]:
    parsed = json.loads(content)
    if not isinstance(parsed, dict):
        raise LlamaCppJSONError("model returned JSON, but not a JSON object")
    return parsed


def _request_for_attempt(request: LLMRequest, attempt: int) -> LLMRequest:
    if attempt <= 1:
        return request
    messages = [message.model_copy() for message in request.messages]
    messages.append(LLMMessage(role=ChatRole.USER, content=JSON_RETRY_INSTRUCTION))
    return request.model_copy(update={"messages": messages})


def _derived_seed(
    campaign_seed: int,
    request: LLMRequest,
    messages: list[LLMMessage],
    response_model: type[BaseModel],
) -> int:
    material = {
        "campaign_seed": campaign_seed,
        "label": request.label,
        "messages": [message.model_dump(mode="json") for message in messages],
        "response_model": response_model.__name__,
    }
    digest = hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).digest()
    return int.from_bytes(digest[:4], "big")


def _stringify_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                value = item.get("text", item.get("content", ""))
                if isinstance(value, str):
                    parts.append(value)
                elif value:
                    parts.append(json.dumps(value, ensure_ascii=False))
            elif item is not None:
                parts.append(str(item))
        return "".join(parts)
    if isinstance(content, dict):
        return json.dumps(content, ensure_ascii=False)
    if content is None:
        return ""
    return str(content)
