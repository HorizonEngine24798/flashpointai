from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import httpx
from pydantic import BaseModel

from crisis_room.config.settings import LlamaCppSettings, load_settings
from crisis_room.llm.contracts import ChatRole, LLMMessage, LLMRequest
from crisis_room.llm.diagnostics import LlamaCppJSONError, LlamaCppStartupError
from crisis_room.llm.diagnostics import LlamaCppTransportError
from crisis_room.llm.llama_cpp_client import (
    LlamaCppServerClient,
    extract_message_content,
)
from crisis_room.llm.prompt_fitting import (
    estimate_chat_tokens,
    fit_messages_to_budget,
)
from crisis_room.llm.smoke import SmokeResponse, build_smoke_request, format_success
from crisis_room.llm.preflight import (
    build_preflight_report,
    format_preflight_report,
    format_start_report,
    start_preflight_server,
    run_preflight_cli,
)
from crisis_room.llm.server_lease import (
    ManagedLlamaServerLease,
    build_server_command,
    parse_endpoint,
    readiness_probe_urls,
    registry_snapshot,
)


class TinyResponse(BaseModel):
    ok: bool
    answer: str


def test_settings_load_env_and_normalize_base_url(monkeypatch) -> None:
    monkeypatch.setenv("CRISIS_ROOM_LLAMACPP_BASE_URL", "http://127.0.0.1:9090")
    monkeypatch.setenv("CRISIS_ROOM_LLAMACPP_MAX_NEW_TOKENS", "256")
    monkeypatch.setenv("CRISIS_ROOM_LLAMACPP_MANAGE_SERVER", "false")

    settings = load_settings().llama_cpp

    assert settings.base_url == "http://127.0.0.1:9090/v1"
    assert settings.max_new_tokens == 256
    assert not settings.manage_server
    assert LlamaCppSettings(base_url="localhost:7777").base_url == "http://localhost:7777/v1"


def test_endpoint_probe_urls_and_command_construction() -> None:
    settings = LlamaCppSettings(
        base_url="http://localhost:8080",
        server_executable="D:/llama/llama-server.exe",
        server_model_path="D:/models/model.gguf",
        server_arguments=["--no-webui", "-np", "1"],
    )

    endpoint = parse_endpoint(settings.base_url)
    command = build_server_command(settings)

    assert endpoint.base_url == "http://localhost:8080/v1"
    assert endpoint.host == "localhost"
    assert endpoint.port == 8080
    assert readiness_probe_urls(settings.base_url) == [
        "http://localhost:8080/v1/models",
        "http://localhost:8080/v1/health",
        "http://localhost:8080/health",
        "http://localhost:8080/v1/health",
    ]
    assert command == [
        "D:\\llama\\llama-server.exe",
        "-m",
        "D:\\models\\model.gguf",
        "--host",
        "localhost",
        "--port",
        "8080",
        "--no-webui",
        "-np",
        "1",
    ]


def test_preflight_report_validates_paths_and_launch_command() -> None:
    directory = _diagnostics_dir("preflight_paths")
    executable = directory / "llama-server.exe"
    model = directory / "model.gguf"
    executable.write_text("", encoding="utf-8")
    model.write_text("", encoding="utf-8")
    settings = LlamaCppSettings(
        base_url="127.0.0.1:8080",
        server_executable=str(executable),
        server_model_path=str(model),
        server_log_dir=str(directory / "logs"),
    )

    report = build_preflight_report(settings, config_source="test config")

    assert report.ok
    assert report.config_source == "test config"
    assert report.normalized_base_url == "http://127.0.0.1:8080/v1"
    assert report.executable.exists
    assert report.model.exists
    assert report.command == build_server_command(settings)
    assert str(directory / "logs") == report.server_log_dir


def test_preflight_report_fails_missing_managed_paths() -> None:
    report = build_preflight_report(LlamaCppSettings())

    assert not report.ok
    assert "llama-server executable is required but not configured" in report.errors
    assert "GGUF model is required but not configured" in report.errors
    rendered = format_preflight_report(report)
    assert "Launch command:" in rendered
    assert "<server_executable>" in rendered
    assert "Result: FAIL" in rendered


def test_preflight_cli_hints_when_git_bash_drops_config_backslash(capsys) -> None:
    exit_code = run_preflight_cli(["--config", "configllama_cpp.local.json"])

    assert exit_code == 2
    output = capsys.readouterr().out
    assert "Did you mean config/llama_cpp.local.json?" in output


def test_preflight_start_calls_lease_and_reports_log_path() -> None:
    directory = _diagnostics_dir("preflight_start")
    log_path = directory / "llama.log"
    instances: list[FakeLease] = []

    def lease_factory(settings: LlamaCppSettings) -> FakeLease:
        lease = FakeLease(log_path=log_path)
        instances.append(lease)
        return lease

    report = start_preflight_server(
        LlamaCppSettings(
            server_executable="D:/llama/llama-server.exe",
            server_model_path="D:/models/model.gguf",
        ),
        lease_factory=lease_factory,
    )

    assert report.ok
    assert report.status == "ready"
    assert report.log_path == str(log_path)
    assert instances[0].ensure_called
    assert instances[0].close_called
    rendered = format_start_report(report)
    assert "managed llama-server is ready" in rendered
    assert str(log_path) in rendered


def test_preflight_start_reports_startup_failure() -> None:
    class FailingLease(FakeLease):
        def ensure_running(self) -> None:
            self.ensure_called = True
            raise LlamaCppStartupError("boom")

    instances: list[FailingLease] = []

    def lease_factory(settings: LlamaCppSettings) -> FailingLease:
        lease = FailingLease(log_path=Path("output/test_diagnostics/failing.log"))
        instances.append(lease)
        return lease

    report = start_preflight_server(
        LlamaCppSettings(
            server_executable="D:/llama/llama-server.exe",
            server_model_path="D:/models/model.gguf",
        ),
        lease_factory=lease_factory,
    )

    assert not report.ok
    assert report.status == "failed"
    assert "LlamaCppStartupError: boom" == report.error
    assert instances[0].close_called


def test_smoke_request_uses_json_object_payload() -> None:
    settings = LlamaCppSettings(manage_server=False, max_new_tokens=512)
    client = LlamaCppServerClient(settings)
    try:
        request = build_smoke_request()
        payload = client.build_payload(request, SmokeResponse)
    finally:
        client.close()

    assert request.response_schema_name is None
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["temperature"] == 0.2
    assert payload["top_p"] == 0.9
    assert payload["max_tokens"] == 128
    assert "json_schema" not in payload


def test_smoke_success_line_includes_model_and_endpoint() -> None:
    settings = LlamaCppSettings(
        base_url="http://127.0.0.1:8080",
        server_model="local-model",
        manage_server=False,
    )

    line = format_success(settings, SmokeResponse(ok=True, answer="hello"))

    assert "llama.cpp smoke OK" in line
    assert "model=local-model" in line
    assert "endpoint=http://127.0.0.1:8080/v1" in line


def test_managed_lease_readiness_probe_treats_os_errors_as_not_ready(monkeypatch) -> None:
    seen_trust_env_values: list[bool] = []

    def raise_file_not_found(
        url: str,
        timeout: httpx.Timeout,
        trust_env: bool,
    ) -> httpx.Response:
        seen_trust_env_values.append(trust_env)
        raise FileNotFoundError("missing probe dependency")

    monkeypatch.setattr("crisis_room.llm.server_lease.httpx.get", raise_file_not_found)
    lease = ManagedLlamaServerLease(LlamaCppSettings(manage_server=False))

    assert not lease._endpoint_is_ready()
    assert seen_trust_env_values
    assert all(value is False for value in seen_trust_env_values)


def test_managed_lease_start_failure_reports_command_and_log(monkeypatch) -> None:
    directory = _diagnostics_dir("lease_start_failure")
    executable = directory / "llama-server.exe"
    model = directory / "model.gguf"
    executable.write_text("", encoding="utf-8")
    model.write_text("", encoding="utf-8")

    def fail_probe(
        url: str,
        timeout: httpx.Timeout,
        trust_env: bool,
    ) -> httpx.Response:
        raise httpx.ConnectError("not up yet")

    def fail_popen(*args: object, **kwargs: object) -> object:
        raise FileNotFoundError("launcher missing dependency")

    monkeypatch.setattr("crisis_room.llm.server_lease.httpx.get", fail_probe)
    monkeypatch.setattr("crisis_room.llm.server_lease.subprocess.Popen", fail_popen)

    settings = LlamaCppSettings(
        server_executable=str(executable),
        server_model_path=str(model),
        server_log_dir=str(directory / "logs"),
    )
    lease = ManagedLlamaServerLease(settings)
    try:
        try:
            lease.ensure_running()
        except LlamaCppStartupError as exc:
            message = str(exc)
        else:
            raise AssertionError("expected startup failure")
    finally:
        lease.close()

    assert "failed to start llama-server" in message
    assert "launcher missing dependency" in message
    assert "command=" in message
    assert str(executable) in message
    assert str(model) in message
    assert lease.log_path is not None
    assert lease.log_path.exists()


def test_prompt_fitting_trims_user_text_first() -> None:
    settings = LlamaCppSettings(
        max_input_tokens=30,
        token_estimation_chars_per_token=2.0,
        manage_server=False,
    )
    messages = [
        LLMMessage(role=ChatRole.SYSTEM, content="Return JSON only."),
        LLMMessage(role=ChatRole.USER, content="x" * 400),
    ]

    fit = fit_messages_to_budget(messages, settings)

    assert fit.was_truncated
    assert "trimmed user message" in fit.truncation_notes
    assert estimate_chat_tokens(fit.messages, settings.token_estimation_chars_per_token) <= 30
    assert fit.messages[0].content == "Return JSON only."


def test_extract_message_content_supports_chunks_and_reasoning_fallback() -> None:
    chunked = {
        "choices": [
            {
                "message": {
                    "content": [
                        {"text": "{\"ok\":"},
                        {"text": "true"},
                        {"text": ",\"answer\":\"hi\"}"},
                    ]
                }
            }
        ]
    }
    reasoning = {
        "choices": [
            {
                "message": {
                    "content": "",
                    "reasoning_content": "{\"ok\":true,\"answer\":\"fallback\"}",
                }
            }
        ]
    }

    assert extract_message_content(chunked) == "{\"ok\":true,\"answer\":\"hi\"}"
    assert extract_message_content(reasoning) == "{\"ok\":true,\"answer\":\"fallback\"}"


def test_llama_cpp_client_validates_json_with_mock_transport() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        assert request.url.path == "/v1/chat/completions"
        assert payload["response_format"] == {"type": "json_object"}
        assert payload["messages"][0]["role"] == "system"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": "{\"ok\":true,\"answer\":\"hello\"}"}}
                ]
            },
        )

    client = LlamaCppServerClient(
        LlamaCppSettings(manage_server=False, max_new_tokens=512),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        diagnostics_dir=_diagnostics_dir("valid_json"),
    )
    request = LLMRequest(
        label="unit_json",
        messages=[
            LLMMessage(role=ChatRole.SYSTEM, content="Return JSON only."),
            LLMMessage(role=ChatRole.USER, content="Say hello."),
        ],
        max_tokens=128,
    )

    response = client.complete_json(request, TinyResponse)

    assert response.ok
    assert response.answer == "hello"
    assert client.calls[0].parsed_response == {"ok": True, "answer": "hello"}
    client.close()


def test_llama_cpp_client_transport_error_includes_label_for_http_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="model is still loading")

    client = LlamaCppServerClient(
        LlamaCppSettings(manage_server=False),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    request = _tiny_request("transport_status")

    try:
        client.complete_json(request, TinyResponse)
    except LlamaCppTransportError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected LlamaCppTransportError")
    finally:
        client.close()

    assert "task_label=transport_status" in message
    assert "status=503" in message
    assert "body_preview=model is still loading" in message


def test_llama_cpp_client_transport_error_includes_label_for_bad_http_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json")

    client = LlamaCppServerClient(
        LlamaCppSettings(manage_server=False),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    request = _tiny_request("transport_bad_http_json")

    try:
        client.complete_json(request, TinyResponse)
    except LlamaCppTransportError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected LlamaCppTransportError")
    finally:
        client.close()

    assert "task_label=transport_bad_http_json" in message
    assert "not valid JSON HTTP payload" in message


def test_llama_cpp_client_transport_error_includes_label_for_non_object_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=["not", "an", "object"])

    client = LlamaCppServerClient(
        LlamaCppSettings(manage_server=False),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    request = _tiny_request("transport_non_object")

    try:
        client.complete_json(request, TinyResponse)
    except LlamaCppTransportError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected LlamaCppTransportError")
    finally:
        client.close()

    assert "task_label=transport_non_object" in message
    assert "HTTP payload was not an object" in message


def test_llama_cpp_client_transport_error_includes_label_for_httpx_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = LlamaCppServerClient(
        LlamaCppSettings(manage_server=False),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    request = _tiny_request("transport_connect")

    try:
        client.complete_json(request, TinyResponse)
    except LlamaCppTransportError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected LlamaCppTransportError")
    finally:
        client.close()

    assert "task_label=transport_connect" in message
    assert "attempt=1" in message
    assert "ConnectError: connection refused" in message


def test_llama_cpp_client_retries_invalid_json_and_writes_diagnostic() -> None:
    diagnostics_dir = _diagnostics_dir("retry_json")
    responses = iter(
        [
            httpx.Response(
                200,
                json={"choices": [{"message": {"content": "not json"}}]},
            ),
            httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": "{\"ok\":true,\"answer\":\"fixed\"}"}}
                    ]
                },
            ),
        ]
    )
    seen_payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_payloads.append(json.loads(request.content.decode("utf-8")))
        return next(responses)

    client = LlamaCppServerClient(
        LlamaCppSettings(manage_server=False, json_retries=1),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        diagnostics_dir=diagnostics_dir,
    )
    request = LLMRequest(
        label="retry_json",
        messages=[
            LLMMessage(role=ChatRole.SYSTEM, content="Return JSON only."),
            LLMMessage(role=ChatRole.USER, content="Return the object."),
        ],
    )

    response = client.complete_json(request, TinyResponse)

    assert response.answer == "fixed"
    assert len(seen_payloads) == 2
    retry_user = seen_payloads[1]["messages"][1]["content"]
    assert "Retry instruction" in retry_user
    assert list(diagnostics_dir.glob("retry_json_1_*.json"))
    client.close()


def test_llama_cpp_client_raises_after_json_retries() -> None:
    diagnostics_dir = _diagnostics_dir("bad_json")
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "still not json"}}]},
        )

    client = LlamaCppServerClient(
        LlamaCppSettings(manage_server=False, json_retries=0),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        diagnostics_dir=diagnostics_dir,
    )
    request = LLMRequest(
        label="bad_json",
        messages=[LLMMessage(role=ChatRole.USER, content="Break contract.")],
        response_schema_name="TinyResponse",
    )

    try:
        client.complete_json(request, TinyResponse)
    except LlamaCppJSONError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected LlamaCppJSONError")
    artifacts = list(diagnostics_dir.glob("bad_json_1_*.json"))
    assert artifacts
    assert "did not satisfy JSON contract" in message
    assert "task_label=bad_json" in message
    assert "schema=TinyResponse" in message
    assert "attempts=1" in message
    assert f"diagnostic_artifact={artifacts[0]}" in message
    client.close()


def test_managed_lease_registry_reference_counts_without_starting() -> None:
    settings = LlamaCppSettings(
        server_executable="D:/llama/llama-server.exe",
        server_model_path="D:/models/model.gguf",
    )

    first = ManagedLlamaServerLease(settings)
    second = ManagedLlamaServerLease(settings)
    try:
        assert first.ref_count == 2
        assert second.ref_count == 2
        assert any(count == 2 for count in registry_snapshot().values())
    finally:
        first.close()
        second.close()


def test_managed_lease_preserves_spawn_ownership_after_repeated_ready_check(
    monkeypatch,
) -> None:
    directory = _diagnostics_dir("lease_auto_stop")
    executable = directory / "llama-server.exe"
    model = directory / "model.gguf"
    executable.write_text("", encoding="utf-8")
    model.write_text("", encoding="utf-8")
    process = FakeProcess()
    readiness_results = iter([False, False, True, True])

    monkeypatch.setattr(
        "crisis_room.llm.server_lease.subprocess.Popen",
        lambda *args, **kwargs: process,
    )
    monkeypatch.setattr(
        ManagedLlamaServerLease,
        "_endpoint_is_ready",
        lambda self: next(readiness_results),
    )

    lease = ManagedLlamaServerLease(
        LlamaCppSettings(
            server_executable=str(executable),
            server_model_path=str(model),
            server_log_dir=str(directory / "logs"),
            server_auto_stop=True,
        )
    )

    lease.ensure_running()
    lease.ensure_running()
    lease.close()

    assert process.terminated
    assert process.wait_called
    assert not process.killed


def test_managed_lease_process_exit_startup_error_includes_log_hint(monkeypatch) -> None:
    directory = _diagnostics_dir("lease_process_exit")
    executable = directory / "llama-server.exe"
    model = directory / "model.gguf"
    executable.write_text("", encoding="utf-8")
    model.write_text("", encoding="utf-8")
    process = FakeProcess()
    process.returncode = 7
    readiness_results = iter([False, False, False])

    monkeypatch.setattr(
        "crisis_room.llm.server_lease.subprocess.Popen",
        lambda *args, **kwargs: process,
    )
    monkeypatch.setattr(
        ManagedLlamaServerLease,
        "_endpoint_is_ready",
        lambda self: next(readiness_results),
    )

    lease = ManagedLlamaServerLease(
        LlamaCppSettings(
            server_executable=str(executable),
            server_model_path=str(model),
            server_log_dir=str(directory / "logs"),
        )
    )
    try:
        try:
            lease.ensure_running()
        except LlamaCppStartupError as exc:
            message = str(exc)
        else:
            raise AssertionError("expected startup failure")
    finally:
        lease.close()

    assert "llama-server exited during startup with code 7" in message
    assert "hint=inspect llama-server log at" in message
    assert str(directory / "logs") in message


def test_managed_lease_timeout_startup_error_includes_log_hint(monkeypatch) -> None:
    directory = _diagnostics_dir("lease_timeout")
    executable = directory / "llama-server.exe"
    model = directory / "model.gguf"
    executable.write_text("", encoding="utf-8")
    model.write_text("", encoding="utf-8")
    process = FakeProcess()
    readiness_results = iter([False, False])

    monkeypatch.setattr(
        "crisis_room.llm.server_lease.subprocess.Popen",
        lambda *args, **kwargs: process,
    )
    monkeypatch.setattr(
        ManagedLlamaServerLease,
        "_endpoint_is_ready",
        lambda self: next(readiness_results),
    )
    monotonic_values = iter([0.0, 1.0])
    monkeypatch.setattr(
        "crisis_room.llm.server_lease.time.monotonic",
        lambda: next(monotonic_values),
    )

    lease = ManagedLlamaServerLease(
        LlamaCppSettings(
            server_executable=str(executable),
            server_model_path=str(model),
            server_log_dir=str(directory / "logs"),
            server_startup_timeout_seconds=0.001,
        )
    )
    try:
        try:
            lease.ensure_running()
        except LlamaCppStartupError as exc:
            message = str(exc)
        else:
            raise AssertionError("expected startup failure")
    finally:
        lease.close()

    assert "llama-server did not become ready" in message
    assert "hint=inspect llama-server log at" in message
    assert str(directory / "logs") in message


def test_managed_lease_rejects_conflicting_same_endpoint_settings() -> None:
    first = ManagedLlamaServerLease(
        LlamaCppSettings(
            server_executable="D:/llama/llama-server.exe",
            server_model_path="D:/models/model-a.gguf",
        )
    )
    try:
        try:
            ManagedLlamaServerLease(
                LlamaCppSettings(
                    server_executable="D:/llama/llama-server.exe",
                    server_model_path="D:/models/model-b.gguf",
                )
            )
        except LlamaCppStartupError as exc:
            assert "conflicting llama-server settings" in str(exc)
        else:
            raise AssertionError("expected endpoint conflict")
    finally:
        first.close()


def _diagnostics_dir(name: str) -> Path:
    path = Path("output") / "test_diagnostics" / f"{name}_{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _tiny_request(label: str) -> LLMRequest:
    return LLMRequest(
        label=label,
        messages=[
            LLMMessage(role=ChatRole.SYSTEM, content="Return JSON only."),
            LLMMessage(role=ChatRole.USER, content="Say hello."),
        ],
        max_tokens=128,
    )


class FakeLease:
    def __init__(self, *, log_path: Path | None) -> None:
        self.log_path = log_path
        self.ensure_called = False
        self.close_called = False

    def ensure_running(self) -> None:
        self.ensure_called = True

    def close(self) -> None:
        self.close_called = True


class FakeProcess:
    def __init__(self) -> None:
        self.returncode: int | None = None
        self.terminated = False
        self.killed = False
        self.wait_called = False

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0

    def wait(self, timeout: float | None = None) -> int:
        self.wait_called = True
        return self.returncode or 0

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9
