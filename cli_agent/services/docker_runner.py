from __future__ import annotations

import json
import re
import subprocess
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cli_agent.models import AppSettings, RunnerResult, RunPaths


ProgressCallback = Callable[[str, str, dict[str, Any] | None], None]
SENSITIVE_ENV_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "AUTHORIZATION")
PACKAGE_EXTRACTION_PATTERN = re.compile(r"Package extraction took (?P<milliseconds>\d+)ms")
MODEL_REQUEST_START = "--- Start of group: Sending request to the AI model ---"
MODEL_REQUEST_END = "--- End of group ---"
MODEL_REQUEST_PHASE = "Copilot model request"
MODEL_REQUEST_POLL_SECONDS = 0.25


class DockerRunner:
    def __init__(self, settings: AppSettings) -> None:
        self._settings = settings
        self._worker_slots = threading.BoundedSemaphore(settings.max_concurrent_worker_runs)

    def build_command(self, run_paths: RunPaths, prompt: str) -> list[str]:
        command = [
            "docker",
            "run",
            "--rm",
            "--init",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,size=64m",
            "--pids-limit=256",
        ]
        if self._settings.docker_network:
            command.extend(["--network", self._settings.docker_network])

        command.extend(_docker_env_args(self._settings))
        command.extend(
            [
                "-v",
                f"{run_paths.root}:/workspace",
                "-w",
                "/workspace/work",
                self._settings.worker_image,
                "copilot",
                "--prompt",
                prompt,
                "--silent",
                "--stream=off",
                "--no-color",
                "--no-auto-update",
                "--no-remote",
                "--disable-builtin-mcps",
                "--disallow-temp-dir",
                "--add-dir=/workspace",
                "--available-tools=view,create,edit,bash,grep,glob",
                "--allow-all-tools",
            ]
        )
        return command

    def run(
        self,
        run_paths: RunPaths,
        prompt: str,
        progress_callback: ProgressCallback | None = None,
    ) -> RunnerResult:
        _emit_progress(
            progress_callback,
            "Docker image build/pull",
            "duration",
            {
                "seconds": 0.0,
                "status": "not run",
                "details": f"The app invokes docker run with existing image {self._settings.worker_image}.",
            },
        )
        _emit_progress(progress_callback, "worker queue wait", "start")
        acquired = self._worker_slots.acquire(timeout=self._settings.worker_queue_timeout_seconds)
        _emit_progress(progress_callback, "worker queue wait", "end")
        if not acquired:
            message = (
                "Worker capacity exceeded. "
                f"Already running {self._settings.max_concurrent_worker_runs} worker(s); "
                f"waited {self._settings.worker_queue_timeout_seconds:g} seconds for a slot."
            )
            _write_runner_logs(run_paths, "", message)
            return RunnerResult(exit_code=125, stdout="", stderr=message, capacity_exceeded=True)

        command = self.build_command(run_paths, prompt)
        _write_docker_command_trace(run_paths, command)
        run_started_at = time.perf_counter()
        model_request_poller = _start_model_request_poller(run_paths, progress_callback)
        try:
            try:
                _emit_progress(progress_callback, "Docker CLI subprocess", "start")
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=self._settings.worker_timeout_seconds,
                    check=False,
                )
                _emit_progress(progress_callback, "Docker CLI subprocess", "end")
            except subprocess.TimeoutExpired as exc:
                _emit_progress(progress_callback, "Docker CLI subprocess", "end")
                _stop_model_request_poller(model_request_poller)
                stdout = _captured_output_text(exc.stdout)
                stderr = _captured_output_text(exc.stderr)
                _write_runner_logs(run_paths, stdout, stderr)
                _emit_worker_diagnostics(run_paths, stderr, time.perf_counter() - run_started_at, progress_callback)
                return RunnerResult(exit_code=124, stdout=stdout, stderr=stderr, timed_out=True)
            except OSError as exc:
                _emit_progress(progress_callback, "Docker CLI subprocess", "end")
                _stop_model_request_poller(model_request_poller)
                stderr = f"Could not start Docker worker: {exc}"
                _write_runner_logs(run_paths, "", stderr)
                return RunnerResult(exit_code=126, stdout="", stderr=stderr)

            _stop_model_request_poller(model_request_poller)
            stdout = _captured_output_text(completed.stdout)
            stderr = _captured_output_text(completed.stderr)
            _write_runner_logs(run_paths, stdout, stderr)
            _emit_worker_diagnostics(run_paths, stderr, time.perf_counter() - run_started_at, progress_callback)
            return RunnerResult(
                exit_code=completed.returncode,
                stdout=stdout,
                stderr=stderr,
                timed_out=False,
            )
        finally:
            _stop_model_request_poller(model_request_poller)
            self._worker_slots.release()


def _docker_env_args(settings: AppSettings) -> list[str]:
    env = {
        "COPILOT_OFFLINE": "true" if settings.copilot_offline else "false",
        "COPILOT_PROVIDER_BASE_URL": settings.copilot_provider_base_url,
        "COPILOT_MODEL": settings.copilot_model,
        "HOME": "/workspace/work/home",
        "XDG_CACHE_HOME": "/workspace/work/cache",
        "XDG_CONFIG_HOME": "/workspace/work/config",
        "COPILOT_HOME": "/workspace/work/copilot-home",
        "COPILOT_CACHE_HOME": "/workspace/work/copilot-cache",
        "COPILOT_AUTO_UPDATE": "false",
        "COPILOT_OTEL_ENABLED": "false",
        "GITHUB_COPILOT_PROMPT_MODE_EXTENSIONS": "false",
        "GITHUB_COPILOT_PROMPT_MODE_REPO_HOOKS": "false",
    }
    if settings.copilot_provider_api_key:
        env["COPILOT_PROVIDER_API_KEY"] = settings.copilot_provider_api_key

    args: list[str] = []
    for name, value in env.items():
        args.extend(["-e", f"{name}={value}"])
    return args


def _captured_output_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _emit_progress(
    progress_callback: ProgressCallback | None,
    phase: str,
    event: str,
    data: dict[str, Any] | None = None,
) -> None:
    if progress_callback is not None:
        progress_callback(phase, event, data)


def _write_docker_command_trace(run_paths: RunPaths, command: list[str]) -> None:
    run_paths.logs_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "note": "This request does not build a Docker image; it runs the configured worker image.",
        "command": _redact_docker_command(command),
    }
    (run_paths.logs_dir / "docker_command.json").write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )


def _redact_docker_command(command: list[str]) -> list[str]:
    redacted: list[str] = []
    skip_prompt_value = False
    for index, part in enumerate(command):
        if skip_prompt_value:
            redacted.append("<see worker_prompt.md>")
            skip_prompt_value = False
            continue
        if part == "--prompt":
            redacted.append(part)
            skip_prompt_value = True
            continue
        if index > 0 and command[index - 1] == "-e":
            redacted.append(_redact_env_assignment(part))
            continue
        redacted.append(part)
    return redacted


def _redact_env_assignment(value: str) -> str:
    name, separator, env_value = value.partition("=")
    if not separator:
        return value
    if any(marker in name.upper() for marker in SENSITIVE_ENV_MARKERS):
        return f"{name}=<redacted>"
    return f"{name}={env_value}"


def _start_model_request_poller(
    run_paths: RunPaths,
    progress_callback: ProgressCallback | None,
) -> tuple[threading.Event, threading.Thread] | None:
    if progress_callback is None:
        return None

    stop_event = threading.Event()
    thread = threading.Thread(
        target=_poll_worker_model_requests,
        args=(run_paths, progress_callback, stop_event),
        daemon=True,
    )
    thread.start()
    return stop_event, thread


def _stop_model_request_poller(poller: tuple[threading.Event, threading.Thread] | None) -> None:
    if poller is None:
        return
    stop_event, thread = poller
    stop_event.set()
    thread.join(timeout=2.0)


def _poll_worker_model_requests(
    run_paths: RunPaths,
    progress_callback: ProgressCallback,
    stop_event: threading.Event,
) -> None:
    emitted_count = 0
    active_request = False
    while not stop_event.wait(MODEL_REQUEST_POLL_SECONDS):
        emitted_count, active_request = _emit_new_model_request_events(
            run_paths,
            progress_callback,
            emitted_count,
            active_request,
        )

    emitted_count, active_request = _emit_new_model_request_events(
        run_paths,
        progress_callback,
        emitted_count,
        active_request,
    )
    if active_request:
        _emit_progress(progress_callback, MODEL_REQUEST_PHASE, "end")


def _emit_new_model_request_events(
    run_paths: RunPaths,
    progress_callback: ProgressCallback,
    emitted_count: int,
    active_request: bool,
) -> tuple[int, bool]:
    events = _model_request_marker_events(run_paths)
    for event in events[emitted_count:]:
        if event["event"] == "start":
            if active_request:
                _emit_progress(progress_callback, MODEL_REQUEST_PHASE, "end")
            _emit_progress(progress_callback, MODEL_REQUEST_PHASE, "start")
            active_request = True
            continue

        if active_request:
            _emit_progress(progress_callback, MODEL_REQUEST_PHASE, "end")
            active_request = False

    return len(events), active_request


def _emit_worker_diagnostics(
    run_paths: RunPaths,
    stderr: str,
    total_seconds: float,
    progress_callback: ProgressCallback | None,
) -> None:
    diagnostics = _worker_diagnostics(run_paths, stderr, total_seconds)
    (run_paths.logs_dir / "worker_diagnostics.json").write_text(
        json.dumps(diagnostics, indent=2),
        encoding="utf-8",
    )
    for row in diagnostics["timing_rows"]:
        _emit_progress(progress_callback, row["phase"], "duration", row)


def _worker_diagnostics(run_paths: RunPaths, stderr: str, total_seconds: float) -> dict[str, Any]:
    package_seconds = _package_extraction_seconds(stderr)
    model_requests = _model_request_durations(run_paths)
    model_total_seconds = sum(request["seconds"] for request in model_requests)
    timing_rows: list[dict[str, Any]] = []

    if package_seconds is not None:
        timing_rows.append(
            {
                "phase": "Copilot package extraction/cache",
                "status": "done",
                "seconds": package_seconds,
                "details": "Parsed from Copilot stderr.",
            }
        )
    if model_requests:
        longest = max(model_requests, key=lambda request: request["seconds"])
        timing_rows.append(
            {
                "phase": "Copilot model requests total",
                "status": "done",
                "seconds": model_total_seconds,
                "details": f"{len(model_requests)} request(s) to the worker model.",
            }
        )
        timing_rows.append(
            {
                "phase": "Longest Copilot model request",
                "status": "done",
                "seconds": longest["seconds"],
                "details": f"{longest['started_at']} -> {longest['ended_at']}",
            }
        )

    known_seconds = model_total_seconds + (package_seconds or 0.0)
    if total_seconds >= known_seconds:
        timing_rows.append(
            {
                "phase": "Worker non-model/tool overhead",
                "status": "estimated",
                "seconds": total_seconds - known_seconds,
                "details": "Docker/Copilot runtime minus parsed package extraction and model request time.",
            }
        )

    return {
        "total_worker_seconds": total_seconds,
        "package_extraction_seconds": package_seconds,
        "model_request_count": len(model_requests),
        "model_requests_total_seconds": model_total_seconds,
        "model_requests": model_requests,
        "timing_rows": timing_rows,
    }


def _package_extraction_seconds(stderr: str) -> float | None:
    match = PACKAGE_EXTRACTION_PATTERN.search(stderr)
    if match is None:
        return None
    return int(match.group("milliseconds")) / 1000


def _model_request_durations(run_paths: RunPaths) -> list[dict[str, Any]]:
    durations: list[dict[str, Any]] = []
    pending_start: dict[str, Any] | None = None
    for event in _model_request_marker_events(run_paths):
        if event["event"] == "start":
            pending_start = event
            continue
        if pending_start is None:
            continue
        started_at = pending_start["timestamp"]
        ended_at = event["timestamp"]
        durations.append(
            {
                "started_at": started_at.isoformat(),
                "ended_at": ended_at.isoformat(),
                "seconds": (ended_at - started_at).total_seconds(),
                "log_path": pending_start["log_path"],
            }
        )
        pending_start = None
    return durations


def _model_request_marker_events(run_paths: RunPaths) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for log_path in sorted((run_paths.work_dir / "copilot-home" / "logs").glob("*.log")):
        for line_number, line in enumerate(log_path.read_text(encoding="utf-8", errors="replace").splitlines()):
            timestamp = _line_timestamp(line)
            if timestamp is None:
                continue
            if MODEL_REQUEST_START in line:
                events.append(
                    {
                        "event": "start",
                        "timestamp": timestamp,
                        "log_path": str(log_path.resolve()),
                        "line_number": line_number,
                    }
                )
                continue
            if MODEL_REQUEST_END in line:
                events.append(
                    {
                        "event": "end",
                        "timestamp": timestamp,
                        "log_path": str(log_path.resolve()),
                        "line_number": line_number,
                    }
                )
    events.sort(key=lambda event: (event["timestamp"], event["log_path"], event["line_number"]))
    return events


def _line_timestamp(line: str) -> datetime | None:
    raw_timestamp = line.split(" ", 1)[0]
    if not raw_timestamp.endswith("Z"):
        return None
    try:
        return datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None


def _write_runner_logs(run_paths: RunPaths, stdout: str, stderr: str) -> None:
    run_paths.logs_dir.mkdir(parents=True, exist_ok=True)
    (run_paths.logs_dir / "copilot.stdout.log").write_text(stdout, encoding="utf-8")
    (run_paths.logs_dir / "copilot.stderr.log").write_text(stderr, encoding="utf-8")
