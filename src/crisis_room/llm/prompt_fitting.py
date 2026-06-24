from __future__ import annotations

from pydantic import BaseModel, Field

from crisis_room.config.settings import LlamaCppSettings
from crisis_room.llm.contracts import ChatRole, LLMMessage


class PromptFitResult(BaseModel):
    messages: list[LLMMessage]
    estimated_input_tokens: int
    was_truncated: bool = False
    truncation_notes: list[str] = Field(default_factory=list)


def estimate_chat_tokens(
    messages: list[LLMMessage],
    chars_per_token: float = 3.0,
) -> int:
    rendered = render_messages_for_estimation(messages)
    ratio = max(1.2, min(8.0, chars_per_token))
    return max(1, round(len(rendered) / ratio))


def render_messages_for_estimation(messages: list[LLMMessage]) -> str:
    lines: list[str] = []
    for message in messages:
        lines.append(f"{message.role.value.title()}:")
        lines.append(message.content)
        lines.append("")
    lines.append("Assistant:")
    return "\n".join(lines)


def fit_messages_to_budget(
    messages: list[LLMMessage],
    settings: LlamaCppSettings,
) -> PromptFitResult:
    fitted = [message.model_copy() for message in messages]
    notes: list[str] = []
    was_truncated = False

    while estimate_chat_tokens(
        fitted,
        settings.token_estimation_chars_per_token,
    ) > settings.max_input_tokens:
        user_index = _longest_message_index(fitted, ChatRole.USER)
        if user_index is not None and fitted[user_index].content:
            fitted[user_index].content = _trim_content(fitted[user_index].content)
            notes.append("trimmed user message")
            was_truncated = True
            continue

        system_index = _longest_message_index(fitted, ChatRole.SYSTEM)
        if system_index is not None and fitted[system_index].content:
            fitted[system_index].content = _trim_content(fitted[system_index].content)
            notes.append("trimmed system message")
            was_truncated = True
            continue
        break

    return PromptFitResult(
        messages=fitted,
        estimated_input_tokens=estimate_chat_tokens(
            fitted,
            settings.token_estimation_chars_per_token,
        ),
        was_truncated=was_truncated,
        truncation_notes=notes,
    )


def _longest_message_index(
    messages: list[LLMMessage],
    role: ChatRole,
) -> int | None:
    candidates = [
        (index, len(message.content))
        for index, message in enumerate(messages)
        if message.role == role and message.content
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[1])[0]


def _trim_content(value: str) -> str:
    if len(value) <= 1:
        return ""
    next_length = max(0, int(len(value) * 0.9))
    return value[:next_length].rstrip()
