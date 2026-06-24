from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import os
import subprocess
import threading
import time
from urllib.parse import urlparse

import httpx

from crisis_room.config.settings import LlamaCppSettings, normalize_llama_base_url
from crisis_room.llm.diagnostics import LlamaCppStartupError


READY_STATUS_CODES = {200, 401, 403}


@dataclass(frozen=True)
class LlamaEndpoint:
    base_url: str
    root_url: str
    host: str
    port: int


@dataclass(frozen=True)
class LeaseKey:
    executable: str
    model_path: str
    host: str
    port: int
    arguments: tuple[str, ...]


@dataclass
class _LeaseState:
    key: LeaseKey
    ref_count: int = 0
    process: subprocess.Popen | None = None
    log_handle: object | None = None
    log_path: Path | None = None
    spawned_by_us: bool = False
    lock: threading.RLock = field(default_factory=threading.RLock)


_REGISTRY_LOCK = threading.RLock()
_REGISTRY: dict[LeaseKey, _LeaseState] = {}


class ManagedLlamaServerLease:
    """Reference-counted lazy lifecycle wrapper for a local llama-server."""

    def __init__(self, settings: LlamaCppSettings) -> None:
        self.settings = settings
        self.endpoint = parse_endpoint(settings.base_url)
        self.enabled = (
            settings.backend == "llama_cpp_server"
            and settings.manage_server
        )
        self._released = False
        self._state: _LeaseState | None = None
        self._key: LeaseKey | None = None
        self._last_readiness_error: str = ""
        if not self.enabled:
            return

        self._key = LeaseKey(
            executable=str(Path(settings.server_executable).expanduser()),
            model_path=str(Path(settings.server_model_path).expanduser()),
            host=self.endpoint.host,
            port=self.endpoint.port,
            arguments=tuple(settings.server_arguments),
        )
        with _REGISTRY_LOCK:
            _raise_on_endpoint_conflict(self._key)
            state = _REGISTRY.get(self._key)
            if state is None:
                state = _LeaseState(key=self._key)
                _REGISTRY[self._key] = state
            state.ref_count += 1
            self._state = state

    def ensure_running(self) -> None:
        if not self.enabled:
            return
        state = self._require_state()
        with state.lock:
            process_running = (
                state.process is not None and state.process.poll() is None
            )
            if self._endpoint_is_ready():
                if not process_running:
                    state.spawned_by_us = False
                return
            if state.process is not None and state.process.poll() is not None:
                self._close_log_handle(state)
                state.process = None
                state.spawned_by_us = False
            if state.process is None:
                if self._endpoint_is_ready():
                    state.spawned_by_us = False
                    return
                self._start_server(state)
            self._wait_until_ready(state)

    def close(self) -> None:
        if not self.enabled or self._released:
            return
        self._released = True
        state = self._require_state()
        should_stop = False
        with _REGISTRY_LOCK:
            state.ref_count = max(0, state.ref_count - 1)
            should_stop = state.ref_count == 0 and self.settings.server_auto_stop
            if state.ref_count == 0 and (self.settings.server_auto_stop or state.process is None):
                _REGISTRY.pop(state.key, None)
        if should_stop:
            with state.lock:
                self._stop_process(state)

    def __enter__(self) -> ManagedLlamaServerLease:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    @property
    def ref_count(self) -> int:
        state = self._state
        return state.ref_count if state is not None else 0

    @property
    def log_path(self) -> Path | None:
        state = self._state
        return state.log_path if state is not None else None

    def _require_state(self) -> _LeaseState:
        if self._state is None:
            raise LlamaCppStartupError("managed llama-server lease is not enabled")
        return self._state

    def _start_server(self, state: _LeaseState) -> None:
        executable = Path(self.settings.server_executable).expanduser()
        model_path = Path(self.settings.server_model_path).expanduser()
        if not executable.exists():
            raise LlamaCppStartupError(f"llama-server executable not found: {executable}")
        if not model_path.exists():
            raise LlamaCppStartupError(f"GGUF model path not found: {model_path}")

        log_dir = Path(self.settings.server_log_dir)
        log_path = log_dir / f"llama_server_{int(time.time())}_{self.endpoint.port}.log"
        state.log_path = log_path
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            log_handle = log_path.open("a", encoding="utf-8")
        except OSError as exc:
            raise LlamaCppStartupError(
                "failed to open llama-server log file; "
                f"endpoint={self.settings.base_url}; "
                f"executable={executable}; model={model_path}; log={log_path}; "
                f"error={type(exc).__name__}: {exc}"
            ) from exc

        log_handle.write(f"endpoint={self.settings.base_url}\n")
        log_handle.write(f"executable={executable}\n")
        log_handle.write(f"model={model_path}\n")
        log_handle.write(f"args={self.settings.server_arguments}\n\n")
        log_handle.flush()
        state.log_handle = log_handle

        command = build_server_command(self.settings, self.endpoint.host, self.endpoint.port)
        creationflags = (
            getattr(subprocess, "CREATE_NO_WINDOW", 0)
            if os.name == "nt"
            else 0
        )
        cwd = str(executable.parent) if executable.parent.exists() else None
        try:
            state.process = subprocess.Popen(
                command,
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                creationflags=creationflags,
            )
        except Exception as exc:
            log_handle.close()
            state.log_handle = None
            raise LlamaCppStartupError(
                "failed to start llama-server; "
                f"endpoint={self.settings.base_url}; "
                f"executable={executable}; model={model_path}; "
                f"cwd={cwd or '(default)'}; log={log_path}; "
                f"command={command}; error={type(exc).__name__}: {exc}"
            ) from exc
        state.spawned_by_us = True

    def _wait_until_ready(self, state: _LeaseState) -> None:
        deadline = time.monotonic() + self.settings.server_startup_timeout_seconds
        while time.monotonic() < deadline:
            if self._endpoint_is_ready():
                return
            if state.process is not None and state.process.poll() is not None:
                raise LlamaCppStartupError(
                    "llama-server exited during startup "
                    f"with code {state.process.returncode}; "
                    f"endpoint={self.settings.base_url}; log={state.log_path}; "
                    f"last_readiness_error={self._last_readiness_error or '(none)'}; "
                    f"{_inspect_log_hint(state.log_path)}"
                )
            time.sleep(self.settings.readiness_poll_interval_seconds)
        raise LlamaCppStartupError(
            f"llama-server did not become ready at {self.settings.base_url}; "
            f"log={state.log_path}; "
            f"last_readiness_error={self._last_readiness_error or '(none)'}; "
            f"{_inspect_log_hint(state.log_path)}"
        )

    def _endpoint_is_ready(self) -> bool:
        self._last_readiness_error = ""
        timeout = httpx.Timeout(
            self.settings.readiness_read_timeout_seconds,
            connect=self.settings.readiness_connect_timeout_seconds,
        )
        for url in readiness_probe_urls(self.settings.base_url):
            try:
                response = httpx.get(url, timeout=timeout, trust_env=False)
            except (httpx.HTTPError, OSError) as exc:
                self._last_readiness_error = (
                    f"{url}: {type(exc).__name__}: {exc}"
                )
                continue
            if response.status_code in READY_STATUS_CODES:
                return True
        return False

    def _stop_process(self, state: _LeaseState) -> None:
        process = state.process
        if process is not None and state.spawned_by_us and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=self.settings.server_shutdown_timeout_seconds)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        state.process = None
        state.spawned_by_us = False
        self._close_log_handle(state)

    def _close_log_handle(self, state: _LeaseState) -> None:
        handle = state.log_handle
        if handle is not None:
            close = getattr(handle, "close", None)
            if callable(close):
                close()
        state.log_handle = None


def parse_endpoint(base_url: str) -> LlamaEndpoint:
    normalized = normalize_llama_base_url(base_url)
    parsed = urlparse(normalized)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8080
    root_url = f"{parsed.scheme or 'http'}://{host}:{port}"
    return LlamaEndpoint(
        base_url=normalized,
        root_url=root_url,
        host=host,
        port=port,
    )


def readiness_probe_urls(base_url: str) -> list[str]:
    endpoint = parse_endpoint(base_url)
    return [
        f"{endpoint.base_url}/models",
        f"{endpoint.base_url}/health",
        f"{endpoint.root_url}/health",
        f"{endpoint.root_url}/v1/health",
    ]


def build_server_command(
    settings: LlamaCppSettings,
    host: str | None = None,
    port: int | None = None,
) -> list[str]:
    endpoint = parse_endpoint(settings.base_url)
    command_host = host or endpoint.host
    command_port = port or endpoint.port
    return [
        str(Path(settings.server_executable).expanduser()),
        "-m",
        str(Path(settings.server_model_path).expanduser()),
        "--host",
        command_host,
        "--port",
        str(command_port),
        *settings.server_arguments,
    ]


def registry_snapshot() -> dict[str, int]:
    with _REGISTRY_LOCK:
        return {repr(key): state.ref_count for key, state in _REGISTRY.items()}


def _raise_on_endpoint_conflict(key: LeaseKey) -> None:
    for existing_key, state in _REGISTRY.items():
        if state.ref_count <= 0:
            continue
        same_endpoint = existing_key.host == key.host and existing_key.port == key.port
        if same_endpoint and existing_key != key:
            raise LlamaCppStartupError(
                "conflicting llama-server settings for endpoint "
                f"{key.host}:{key.port}; existing={existing_key}; requested={key}"
            )


def _inspect_log_hint(log_path: Path | None) -> str:
    if log_path is None:
        return "hint=inspect the llama-server log path printed during startup"
    return f"hint=inspect llama-server log at {log_path}"
