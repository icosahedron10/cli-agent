from __future__ import annotations

import base64
import json
import mimetypes
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlparse

from cli_agent.app_factory import build_chat_controller
from cli_agent.controllers.chat_controller import ProgressCallback
from cli_agent.models import AppSettings, ChatTurnResult, ToolEnvelope
from cli_agent.services.approved_sources import ApprovedSourceService
from cli_agent.settings import load_app_settings


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
MAX_REQUEST_BYTES = 1_000_000
TERMINAL_JOB_STATUSES = {"complete", "error"}


@dataclass
class ApiJob:
    request_id: str
    timing_state: dict[str, Any] = field(default_factory=lambda: {"completed": [], "active": {}})
    timing_lock: threading.Lock = field(default_factory=threading.Lock)
    result: dict[str, Any] | None = None
    error: str | None = None
    status: str = "running"


@dataclass
class ApiState:
    settings: AppSettings
    controller: Any
    approved_sources: ApprovedSourceService
    cors_origin: str = "*"
    jobs: dict[str, ApiJob] = field(default_factory=dict)
    jobs_lock: threading.Lock = field(default_factory=threading.Lock)


class ApiError(Exception):
    def __init__(self, status: HTTPStatus, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def build_api_state(cors_origin: str | None = None) -> ApiState:
    settings = load_app_settings()
    controller, approved_sources = build_chat_controller()
    return ApiState(
        settings=settings,
        controller=controller,
        approved_sources=approved_sources,
        cors_origin=cors_origin or os.getenv("CLI_AGENT_HTTP_CORS_ORIGIN", "*"),
    )


def run_http_api(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    state: ApiState | None = None,
) -> None:
    server = ThreadingHTTPServer((host, port), CliAgentRequestHandler)
    server.api_state = state or build_api_state()  # type: ignore[attr-defined]
    print(f"cli-agent HTTP API listening on http://{host}:{port}", flush=True)
    server.serve_forever()


class CliAgentRequestHandler(BaseHTTPRequestHandler):
    server_version = "CliAgentHTTP/0.1"

    def do_OPTIONS(self) -> None:
        self._send_empty(HTTPStatus.NO_CONTENT)

    def do_GET(self) -> None:
        try:
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            if path == "/health":
                self._send_json({"status": "ok"})
                return
            if path == "/sources":
                self._send_json({"sources": _source_payloads(_state(self).approved_sources)})
                return
            if path.startswith("/runs/") and path.endswith("/events"):
                self._send_json(_job_events_payload(_state(self), _path_part(path, 1)))
                return
            if path.startswith("/artifacts/"):
                self._send_artifact(path)
                return
            raise ApiError(HTTPStatus.NOT_FOUND, "Unknown endpoint")
        except ApiError as exc:
            self._send_error(exc.status, exc.message)
        except Exception as exc:
            self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def do_POST(self) -> None:
        try:
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            if path != "/chat":
                raise ApiError(HTTPStatus.NOT_FOUND, "Unknown endpoint")
            payload = self._read_json()
            history = payload.get("messages", [])
            prompt = payload.get("prompt")
            if not isinstance(history, list):
                raise ApiError(HTTPStatus.BAD_REQUEST, "messages must be a list")
            if not isinstance(prompt, str) or not prompt.strip():
                raise ApiError(HTTPStatus.BAD_REQUEST, "prompt must be a non-empty string")
            job = _start_chat_job(_state(self), history, prompt.strip())
            self._send_json(
                {
                    "request_id": job.request_id,
                    "events_url": f"/runs/{quote(job.request_id)}/events",
                    "status": job.status,
                },
                status=HTTPStatus.ACCEPTED,
            )
        except ApiError as exc:
            self._send_error(exc.status, exc.message)
        except Exception as exc:
            self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ApiError(HTTPStatus.BAD_REQUEST, "Content-Length must be an integer") from exc
        if length <= 0:
            raise ApiError(HTTPStatus.BAD_REQUEST, "Request body is required")
        if length > MAX_REQUEST_BYTES:
            raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Request body is too large")
        raw = self.rfile.read(length)
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ApiError(HTTPStatus.BAD_REQUEST, "Request body must be valid JSON") from exc
        if not isinstance(decoded, dict):
            raise ApiError(HTTPStatus.BAD_REQUEST, "Request body must be a JSON object")
        return decoded

    def _send_artifact(self, path: str) -> None:
        parts = [unquote(part) for part in path.split("/") if part]
        if len(parts) != 3:
            raise ApiError(HTTPStatus.NOT_FOUND, "Artifact route must include run id and file id")
        _, run_id, file_id = parts
        target = _artifact_path_from_id(_state(self).settings, run_id, file_id)
        content_type = _content_type(target)
        disposition = "attachment" if target.suffix.lower() == ".csv" else "inline"
        data = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self._send_common_headers(content_type)
        self.send_header("Content-Disposition", f'{disposition}; filename="{target.name}"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8")
        self.send_response(status)
        self._send_common_headers("application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_error(self, status: HTTPStatus, message: str) -> None:
        self._send_json({"error": message}, status=status)

    def _send_empty(self, status: HTTPStatus) -> None:
        self.send_response(status)
        self._send_common_headers("text/plain; charset=utf-8")
        self.end_headers()

    def _send_common_headers(self, content_type: str) -> None:
        state = _state(self)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", state.cors_origin)
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Vary", "Origin")


def _state(handler: BaseHTTPRequestHandler) -> ApiState:
    return handler.server.api_state  # type: ignore[attr-defined,return-value]


def _path_part(path: str, index: int) -> str:
    parts = [unquote(part) for part in path.split("/") if part]
    try:
        return parts[index]
    except IndexError as exc:
        raise ApiError(HTTPStatus.NOT_FOUND, "Malformed path") from exc


def _source_payloads(approved_sources: ApprovedSourceService) -> list[dict[str, Any]]:
    return [
        {
            "path": source.path,
            "label": source.label,
            "description": source.description,
            "size_bytes": source.size_bytes,
        }
        for source in approved_sources.all_sources()
    ]


def _start_chat_job(state: ApiState, history: list[dict[str, Any]], prompt: str) -> ApiJob:
    job = ApiJob(request_id=f"chat-{uuid.uuid4().hex[:12]}")
    with state.jobs_lock:
        _evict_jobs_locked(state, max(0, state.settings.max_api_jobs - 1))
        state.jobs[job.request_id] = job

    worker = threading.Thread(
        target=_run_chat_job,
        args=(state, job, history, prompt),
        daemon=True,
    )
    worker.start()
    return job


def _run_chat_job(state: ApiState, job: ApiJob, history: list[dict[str, Any]], prompt: str) -> None:
    def progress_callback(phase: str, event: str, data: dict[str, Any] | None = None) -> None:
        _record_progress_event(job, phase, event, data)

    try:
        result = state.controller.handle_user_turn(history, prompt, progress_callback=progress_callback)
        payload = _chat_result_payload(state.settings, result)
        with job.timing_lock:
            job.result = payload
            job.status = "complete"
    except Exception as exc:
        with job.timing_lock:
            job.error = str(exc)
            job.status = "error"
    finally:
        _evict_jobs(state, protected_request_id=job.request_id)


def _evict_jobs(state: ApiState, protected_request_id: str | None = None) -> None:
    with state.jobs_lock:
        _evict_jobs_locked(state, state.settings.max_api_jobs, protected_request_id)


def _evict_jobs_locked(
    state: ApiState,
    target_count: int,
    protected_request_id: str | None = None,
) -> None:
    if len(state.jobs) <= target_count:
        return
    for request_id, job in list(state.jobs.items()):
        if len(state.jobs) <= target_count:
            return
        if request_id == protected_request_id:
            continue
        with job.timing_lock:
            status = job.status
        if status in TERMINAL_JOB_STATUSES:
            state.jobs.pop(request_id, None)
    for request_id in list(state.jobs):
        if len(state.jobs) <= target_count:
            return
        if request_id != protected_request_id:
            state.jobs.pop(request_id, None)


def _record_progress_event(
    job: ApiJob,
    phase: str,
    event: str,
    data: dict[str, Any] | None = None,
) -> None:
    now = time.perf_counter()
    with job.timing_lock:
        active = job.timing_state["active"]
        completed = job.timing_state["completed"]
        if event == "duration":
            completed.append(
                {
                    "phase": phase,
                    "status": (data or {}).get("status", "done"),
                    "seconds": float((data or {}).get("seconds", 0.0)),
                    "details": (data or {}).get("details", ""),
                }
            )
            return
        if event == "start":
            active[phase] = now
            return
        if event != "end":
            return
        started_at = active.pop(phase, None)
        if started_at is None:
            return
        completed.append(
            {
                "phase": phase,
                "status": "done",
                "seconds": now - started_at,
                "details": "",
            }
        )


def _job_events_payload(state: ApiState, request_id: str) -> dict[str, Any]:
    with state.jobs_lock:
        job = state.jobs.get(request_id)
    if job is None:
        raise ApiError(HTTPStatus.NOT_FOUND, "Unknown run id")
    with job.timing_lock:
        status = job.status
        result = job.result
        error = job.error
        timings = _timing_rows(job)
    return {
        "request_id": request_id,
        "status": status,
        "timings": timings,
        "result": result,
        "error": error,
    }


def _timing_rows(job: ApiJob) -> list[dict[str, Any]]:
    now = time.perf_counter()
    rows = [dict(row) for row in job.timing_state["completed"]]
    rows.extend(
        {
            "phase": phase,
            "status": "running",
            "seconds": now - started_at,
            "details": "",
        }
        for phase, started_at in job.timing_state["active"].items()
    )
    rows.sort(key=lambda row: row["seconds"], reverse=True)
    for row in rows:
        row["seconds"] = round(float(row["seconds"]), 1)
    return rows


def _chat_result_payload(settings: AppSettings, result: ChatTurnResult) -> dict[str, Any]:
    return {
        "messages": [_message_payload(settings, message) for message in result.messages],
        "assistant_message": _message_payload(settings, result.assistant_message),
        "tool_envelopes": [_tool_envelope_payload(settings, envelope) for envelope in result.tool_envelopes],
    }


def _message_payload(settings: AppSettings, message: dict[str, Any]) -> dict[str, Any]:
    payload = dict(message)
    if payload.get("role") != "tool" or not isinstance(payload.get("content"), str):
        return payload
    try:
        decoded = json.loads(payload["content"])
    except json.JSONDecodeError:
        return payload
    if not isinstance(decoded, dict):
        return payload
    payload["content"] = json.dumps(_tool_payload(settings, decoded), separators=(",", ":"))
    return payload


def _tool_envelope_payload(settings: AppSettings, envelope: ToolEnvelope) -> dict[str, Any]:
    return _tool_payload(settings, envelope.to_model_json())


def _tool_payload(settings: AppSettings, payload: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(payload)
    run_id = sanitized.get("run_id")
    artifact_paths = sanitized.pop("artifact_paths", []) or []
    trace_paths = sanitized.pop("trace_paths", []) or []
    sanitized["artifact_paths"] = []
    sanitized["trace_paths"] = []
    sanitized["artifacts"] = _file_references(settings, run_id, artifact_paths, "artifact")
    sanitized["traces"] = _file_references(settings, run_id, trace_paths, "trace")
    return sanitized


def _file_references(
    settings: AppSettings,
    run_id: Any,
    raw_paths: Any,
    kind: str,
) -> list[dict[str, Any]]:
    if not raw_paths:
        return []
    if not isinstance(run_id, str) or not run_id:
        raise ValueError(f"Cannot expose {kind} files without a run id")
    if not isinstance(raw_paths, list) or not all(isinstance(path, str) for path in raw_paths):
        raise ValueError(f"{kind} paths must be strings")
    return [_file_reference(settings, run_id, Path(raw_path), kind) for raw_path in raw_paths]


def _file_reference(settings: AppSettings, run_id: str, path: Path, kind: str) -> dict[str, Any]:
    run_root = (settings.runs_root / run_id).resolve()
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(run_root)
    except ValueError as exc:
        raise ValueError(f"{kind} path escapes run folder: {path}") from exc
    file_id = _encode_file_id(relative.as_posix())
    return {
        "id": file_id,
        "name": resolved.name,
        "kind": kind,
        "mime_type": _content_type(resolved),
        "size_bytes": resolved.stat().st_size if resolved.exists() else 0,
        "url": f"/artifacts/{quote(run_id)}/{quote(file_id)}",
    }


def _artifact_path_from_id(settings: AppSettings, run_id: str, file_id: str) -> Path:
    runs_root_resolved = settings.runs_root.resolve()
    run_root = (settings.runs_root / run_id).resolve()
    try:
        run_root.relative_to(runs_root_resolved)
    except ValueError as exc:
        raise ApiError(HTTPStatus.FORBIDDEN, "Run id is outside the runs folder") from exc
    if not run_root.exists() or not run_root.is_dir():
        raise ApiError(HTTPStatus.NOT_FOUND, "Run folder does not exist")
    relative = Path(_decode_file_id(file_id))
    if relative.is_absolute() or ".." in relative.parts:
        raise ApiError(HTTPStatus.FORBIDDEN, "Artifact path is outside the run folder")
    target = (run_root / relative).resolve()
    try:
        target.relative_to(run_root)
    except ValueError as exc:
        raise ApiError(HTTPStatus.FORBIDDEN, "Artifact path is outside the run folder") from exc
    if not target.is_file():
        raise ApiError(HTTPStatus.NOT_FOUND, "Artifact file does not exist")
    return target


def _encode_file_id(relative_path: str) -> str:
    raw = base64.urlsafe_b64encode(relative_path.encode("utf-8")).decode("ascii")
    return raw.rstrip("=")


def _decode_file_id(file_id: str) -> str:
    padding = "=" * (-len(file_id) % 4)
    try:
        return base64.urlsafe_b64decode((file_id + padding).encode("ascii")).decode("utf-8")
    except (UnicodeDecodeError, ValueError) as exc:
        raise ApiError(HTTPStatus.BAD_REQUEST, "Artifact id is invalid") from exc


def _content_type(path: Path) -> str:
    if path.suffix.lower() == ".md":
        return "text/markdown; charset=utf-8"
    if path.suffix.lower() == ".jsonl":
        return "application/x-ndjson; charset=utf-8"
    guessed, _ = mimetypes.guess_type(path.name)
    if guessed:
        if guessed.startswith("text/") or guessed == "application/json":
            return f"{guessed}; charset=utf-8"
        return guessed
    return "application/octet-stream"


def main() -> None:
    host = os.getenv("CLI_AGENT_HTTP_HOST", DEFAULT_HOST)
    port = int(os.getenv("CLI_AGENT_HTTP_PORT", str(DEFAULT_PORT)))
    run_http_api(host=host, port=port)


if __name__ == "__main__":
    main()
