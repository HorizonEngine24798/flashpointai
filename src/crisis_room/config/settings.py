from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator


DEFAULT_SERVER_ARGUMENTS = [
    "--no-webui",
    "--reasoning",
    "off",
    "-ngl",
    "all",
    "-c",
    "65536",
    "-np",
    "1",
]

DEFAULT_LOCAL_CONFIG_PATH = Path("config/llama_cpp.local.json")


class LlamaCppSettings(BaseModel):
    backend: str = "llama_cpp_server"
    preset: str = "qwen3.5-35b-uncensored"
    base_url: str = "http://127.0.0.1:8080/v1"
    server_model: str = "Qwen3.5-35B-A3B-Q3_K_M"
    max_input_tokens: int = Field(default=40960, ge=1)
    max_new_tokens: int = Field(default=8192, ge=1)
    token_estimation_chars_per_token: float = Field(default=3.0, gt=0.0)
    json_retries: int = Field(default=1, ge=0)
    manage_server: bool = True
    server_executable: str = ""
    server_model_path: str = ""
    server_arguments: list[str] = Field(default_factory=lambda: list(DEFAULT_SERVER_ARGUMENTS))
    server_log_dir: str = "output/diagnostics/llama_server"
    server_startup_timeout_seconds: float = Field(default=180.0, gt=0.0)
    server_shutdown_timeout_seconds: float = Field(default=15.0, gt=0.0)
    server_auto_stop: bool = True
    request_timeout_seconds: float = Field(default=300.0, gt=0.0)
    readiness_connect_timeout_seconds: float = Field(default=0.5, gt=0.0)
    readiness_read_timeout_seconds: float = Field(default=1.2, gt=0.0)
    readiness_poll_interval_seconds: float = Field(default=0.4, gt=0.0)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    top_p: float = Field(default=0.9, ge=0.0, le=1.0)

    @field_validator("base_url")
    @classmethod
    def normalize_base_url(cls, value: str) -> str:
        return normalize_llama_base_url(value)

    @property
    def chat_completions_url(self) -> str:
        return f"{self.base_url}/chat/completions"


class AppSettings(BaseModel):
    llama_cpp: LlamaCppSettings = Field(default_factory=LlamaCppSettings)


def load_settings(config_path: str | Path | None = None) -> AppSettings:
    """Load settings from JSON config plus CRISIS_ROOM_* environment overrides."""

    data: dict[str, Any] = {}
    path = resolve_settings_path(config_path)
    if path:
        config_file = Path(path)
        if config_file.exists():
            loaded = json.loads(config_file.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded

    llama_data = _extract_llama_config(data)
    llama_data.update(_llama_env_overrides())
    return AppSettings(llama_cpp=LlamaCppSettings.model_validate(llama_data))


def resolve_settings_path(config_path: str | Path | None = None) -> Path | None:
    if config_path is not None:
        return Path(config_path)
    env_path = os.getenv("CRISIS_ROOM_CONFIG_PATH")
    if env_path:
        return Path(env_path)
    if DEFAULT_LOCAL_CONFIG_PATH.exists():
        return DEFAULT_LOCAL_CONFIG_PATH
    return None


def normalize_llama_base_url(value: str) -> str:
    base = (value or "http://127.0.0.1:8080/v1").strip().rstrip("/")
    if not base.startswith(("http://", "https://")):
        base = f"http://{base}"
    if not base.endswith("/v1"):
        base = f"{base}/v1"
    return base


def _extract_llama_config(data: dict[str, Any]) -> dict[str, Any]:
    if "llama_cpp" in data and isinstance(data["llama_cpp"], dict):
        return dict(data["llama_cpp"])
    return {
        key: value
        for key, value in data.items()
        if key in LlamaCppSettings.model_fields
    }


def _llama_env_overrides() -> dict[str, Any]:
    prefix = "CRISIS_ROOM_LLAMACPP_"
    field_map = {
        "BASE_URL": "base_url",
        "SERVER_MODEL": "server_model",
        "SERVER_EXECUTABLE": "server_executable",
        "SERVER_MODEL_PATH": "server_model_path",
        "MANAGE_SERVER": "manage_server",
        "SERVER_AUTO_STOP": "server_auto_stop",
        "MAX_INPUT_TOKENS": "max_input_tokens",
        "MAX_NEW_TOKENS": "max_new_tokens",
        "JSON_RETRIES": "json_retries",
        "REQUEST_TIMEOUT_SECONDS": "request_timeout_seconds",
        "TEMPERATURE": "temperature",
        "TOP_P": "top_p",
    }
    overrides: dict[str, Any] = {}
    for env_suffix, field_name in field_map.items():
        raw = os.getenv(f"{prefix}{env_suffix}")
        if raw is None or raw == "":
            continue
        overrides[field_name] = _coerce_env_value(raw)
    return overrides


def _coerce_env_value(value: str) -> str | int | float | bool:
    lowered = value.lower()
    if lowered in {"true", "1", "yes", "on"}:
        return True
    if lowered in {"false", "0", "no", "off"}:
        return False
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value
