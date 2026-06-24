from __future__ import annotations

import argparse
from typing import Sequence

from pydantic import BaseModel

from crisis_room.config.settings import LlamaCppSettings, load_settings
from crisis_room.llm.contracts import ChatRole, LLMMessage, LLMRequest
from crisis_room.llm.llama_cpp_client import LlamaCppServerClient


class SmokeResponse(BaseModel):
    ok: bool
    answer: str


def build_smoke_request() -> LLMRequest:
    return LLMRequest(
        label="llama_cpp_live_smoke",
        messages=[
            LLMMessage(
                role=ChatRole.SYSTEM,
                content="Return exactly one JSON object and no other text.",
            ),
            LLMMessage(
                role=ChatRole.USER,
                content='Return {"ok": true, "answer": "hello"} and nothing else.',
            ),
        ],
        temperature=0.2,
        top_p=0.9,
        max_tokens=128,
    )


def format_success(settings: LlamaCppSettings, response: SmokeResponse) -> str:
    return (
        "llama.cpp smoke OK: "
        f"model={settings.server_model} endpoint={settings.base_url} "
        f"response={{ok={str(response.ok).lower()}, answer={response.answer!r}}}"
    )


def run_smoke(settings: LlamaCppSettings) -> SmokeResponse:
    request = build_smoke_request()
    with LlamaCppServerClient(settings) as client:
        return client.complete_json(request, SmokeResponse)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Run a live llama.cpp JSON contract smoke test."
    )
    parser.add_argument(
        "--config",
        default=None,
        help=(
            "path to a config JSON; defaults to CRISIS_ROOM_CONFIG_PATH, "
            "config/llama_cpp.local.json, or built-in defaults"
        ),
    )
    args = parser.parse_args(argv)

    settings = load_settings(args.config).llama_cpp
    response = run_smoke(settings)
    print(format_success(settings, response))


if __name__ == "__main__":
    main()
