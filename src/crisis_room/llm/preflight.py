from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable, Sequence

from crisis_room.config.settings import (
    DEFAULT_LOCAL_CONFIG_PATH,
    LlamaCppSettings,
    load_settings,
)
from crisis_room.llm.server_lease import (
    ManagedLlamaServerLease,
    build_server_command,
    parse_endpoint,
    readiness_probe_urls,
)


@dataclass(frozen=True)
class PathCheck:
    label: str
    raw_value: str
    resolved_value: str
    exists: bool
    required: bool


@dataclass(frozen=True)
class LlamaPreflightReport:
    config_source: str
    backend: str
    preset: str
    server_model: str
    manage_server: bool
    normalized_base_url: str
    root_url: str
    executable: PathCheck
    model: PathCheck
    command: list[str]
    server_log_dir: str
    readiness_urls: list[str]
    errors: list[str]
    warnings: list[str]

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class LlamaPreflightStartReport:
    ok: bool
    status: str
    message: str
    log_path: str
    error: str


LeaseFactory = Callable[[LlamaCppSettings], Any]


def build_preflight_report(
    settings: LlamaCppSettings,
    *,
    config_source: str = "defaults",
    extra_errors: Sequence[str] | None = None,
) -> LlamaPreflightReport:
    endpoint = parse_endpoint(settings.base_url)
    requires_local_paths = settings.backend == "llama_cpp_server" and settings.manage_server
    executable = _path_check(
        "llama-server executable",
        settings.server_executable,
        required=requires_local_paths,
    )
    model = _path_check(
        "GGUF model",
        settings.server_model_path,
        required=requires_local_paths,
    )
    errors = list(extra_errors or [])
    warnings: list[str] = []

    if settings.backend != "llama_cpp_server":
        errors.append(f"unsupported llama_cpp.backend: {settings.backend}")
    if settings.manage_server:
        _append_path_errors(errors, executable)
        _append_path_errors(errors, model)
    else:
        warnings.append(
            "manage_server=false; executable and model paths are not required "
            "because the app will attach to an existing server."
        )

    return LlamaPreflightReport(
        config_source=config_source,
        backend=settings.backend,
        preset=settings.preset,
        server_model=settings.server_model,
        manage_server=settings.manage_server,
        normalized_base_url=endpoint.base_url,
        root_url=endpoint.root_url,
        executable=executable,
        model=model,
        command=_display_server_command(settings),
        server_log_dir=_resolved_path_text(settings.server_log_dir),
        readiness_urls=readiness_probe_urls(settings.base_url),
        errors=errors,
        warnings=warnings,
    )


def format_preflight_report(
    report: LlamaPreflightReport,
    *,
    start_requested: bool = False,
) -> str:
    mode_line = (
        "This validates configuration and then starts or attaches to llama-server "
        "because --start was passed."
        if start_requested
        else "This validates configuration and file paths only; it does not start llama-server."
    )
    lines = [
        "llama.cpp local config preflight",
        mode_line,
        "",
        f"Config source: {report.config_source}",
        f"Backend: {report.backend}",
        f"Preset: {report.preset}",
        f"Base URL: {report.normalized_base_url}",
        f"Root URL: {report.root_url}",
        f"Server model label: {report.server_model}",
        f"Manage server: {str(report.manage_server).lower()}",
        f"Executable: {_format_path_check(report.executable)}",
        f"Model file: {_format_path_check(report.model)}",
        f"Server log directory: {report.server_log_dir}",
        "",
        "Launch command:",
        f"  {format_command(report.command)}",
        "",
        "Readiness probe URLs:",
        *[f"  {url}" for url in report.readiness_urls],
    ]
    if report.warnings:
        lines.extend(["", "Warnings:", *[f"  - {warning}" for warning in report.warnings]])
    if report.errors:
        lines.extend(["", "Errors:", *[f"  - {error}" for error in report.errors]])
    lines.extend(["", f"Result: {'OK' if report.ok else 'FAIL'}"])
    return "\n".join(lines)


def format_start_report(report: LlamaPreflightStartReport) -> str:
    lines = [
        "",
        "Start check:",
        f"  Status: {report.status}",
        f"  Message: {report.message}",
        f"  Server log path: {report.log_path or '(none)'}",
    ]
    if report.error:
        lines.append(f"  Error: {report.error}")
    return "\n".join(lines)


def format_command(command: Sequence[str]) -> str:
    return subprocess.list2cmdline([str(part) for part in command])


def start_preflight_server(
    settings: LlamaCppSettings,
    *,
    lease_factory: LeaseFactory = ManagedLlamaServerLease,
) -> LlamaPreflightStartReport:
    lease: Any | None = None
    try:
        lease = lease_factory(settings)
        lease.ensure_running()
        raw_log_path = getattr(lease, "log_path", None)
        log_path = str(raw_log_path) if raw_log_path is not None else ""
        if not settings.manage_server:
            message = (
                "manage_server=false; no managed process was started. "
                "Use the readiness URLs above to check your manual server."
            )
            status = "not-started"
        elif log_path:
            message = "managed llama-server is ready"
            status = "ready"
        else:
            message = "endpoint is already ready; attached to existing server"
            status = "ready"
        return LlamaPreflightStartReport(
            ok=True,
            status=status,
            message=message,
            log_path=log_path,
            error="",
        )
    except Exception as exc:
        raw_log_path = getattr(lease, "log_path", None) if lease is not None else None
        return LlamaPreflightStartReport(
            ok=False,
            status="failed",
            message="llama-server did not become ready",
            log_path=str(raw_log_path) if raw_log_path is not None else "",
            error=f"{type(exc).__name__}: {exc}",
        )
    finally:
        close = getattr(lease, "close", None) if lease is not None else None
        if callable(close):
            close()


def run_preflight_cli(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate local llama.cpp server configuration without starting the model."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help=(
            "path to a config JSON; defaults to CRISIS_ROOM_CONFIG_PATH, "
            "config/llama_cpp.local.json, or built-in defaults"
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print the preflight report as JSON",
    )
    parser.add_argument(
        "--start",
        action="store_true",
        help="after validation, start or attach to llama-server with the managed lease",
    )
    args = parser.parse_args(argv)

    config_source, config_errors = _config_source(args.config)
    try:
        settings = load_settings(args.config).llama_cpp
    except Exception as exc:
        message = f"failed to load llama.cpp settings: {type(exc).__name__}: {exc}"
        if args.json:
            print(json.dumps({"ok": False, "errors": [message]}, indent=2))
        else:
            print(message, file=sys.stderr)
        return 2

    report = build_preflight_report(
        settings,
        config_source=config_source,
        extra_errors=config_errors,
    )
    start_report: LlamaPreflightStartReport | None = None
    if args.start and report.ok:
        start_report = start_preflight_server(settings)
    elif args.start:
        start_report = LlamaPreflightStartReport(
            ok=False,
            status="skipped",
            message="configuration preflight failed; server startup was skipped",
            log_path="",
            error="",
        )

    ok = report.ok and (start_report is None or start_report.ok)
    if args.json:
        data = asdict(report)
        if start_report is not None:
            data["start"] = asdict(start_report)
        data["ok"] = ok
        print(json.dumps(data, indent=2))
    else:
        print(format_preflight_report(report, start_requested=args.start))
        if start_report is not None:
            print(format_start_report(start_report))
    return 0 if ok else 2


def main(argv: Sequence[str] | None = None) -> None:
    raise SystemExit(run_preflight_cli(argv))


def _path_check(label: str, raw_value: str, *, required: bool) -> PathCheck:
    raw = (raw_value or "").strip()
    resolved = _resolved_path_text(raw) if raw else ""
    exists = bool(raw) and Path(raw).expanduser().exists()
    return PathCheck(
        label=label,
        raw_value=raw,
        resolved_value=resolved,
        exists=exists,
        required=required,
    )


def _append_path_errors(errors: list[str], check: PathCheck) -> None:
    if not check.required:
        return
    if not check.raw_value:
        errors.append(f"{check.label} is required but not configured")
    elif not check.exists:
        errors.append(f"{check.label} was not found: {check.resolved_value}")


def _display_server_command(settings: LlamaCppSettings) -> list[str]:
    if settings.server_executable.strip() and settings.server_model_path.strip():
        return build_server_command(settings)
    endpoint = parse_endpoint(settings.base_url)
    executable = settings.server_executable.strip() or "<server_executable>"
    model_path = settings.server_model_path.strip() or "<server_model_path>"
    return [
        _resolved_path_text(executable),
        "-m",
        _resolved_path_text(model_path),
        "--host",
        endpoint.host,
        "--port",
        str(endpoint.port),
        *settings.server_arguments,
    ]


def _resolved_path_text(value: str) -> str:
    return str(Path(value).expanduser())


def _format_path_check(check: PathCheck) -> str:
    requirement = "required" if check.required else "optional"
    path_text = check.resolved_value or "(not configured)"
    if not check.raw_value:
        status = "missing" if check.required else "not configured"
    elif check.exists:
        status = "exists"
    else:
        status = "not found"
    return f"[{status}] {path_text} ({requirement})"


def _config_source(config_path: Path | None) -> tuple[str, list[str]]:
    if config_path is not None:
        return _config_source_from_path(config_path, "CLI --config")
    env_path = os.getenv("CRISIS_ROOM_CONFIG_PATH")
    if env_path:
        return _config_source_from_path(Path(env_path), "CRISIS_ROOM_CONFIG_PATH")
    if DEFAULT_LOCAL_CONFIG_PATH.exists():
        return _config_source_from_path(DEFAULT_LOCAL_CONFIG_PATH, "default local config")
    return "built-in defaults", []


def _config_source_from_path(path: Path, label: str) -> tuple[str, list[str]]:
    resolved = path.expanduser()
    errors = []
    if not resolved.exists():
        message = f"config file was not found: {resolved}"
        hint = _missing_config_path_hint(str(path))
        if hint:
            message = f"{message}. {hint}"
        errors.append(message)
    return f"{label}: {resolved}", errors


def _missing_config_path_hint(raw_path: str) -> str:
    if "\\" in raw_path:
        return "If you are using Git Bash, pass the path with forward slashes."
    if raw_path.startswith("config") and not raw_path.startswith(("config/", "config\\")):
        candidate = Path("config") / raw_path.removeprefix("config")
        if candidate.exists():
            return f"Did you mean {candidate.as_posix()}?"
    return ""


if __name__ == "__main__":
    main()
