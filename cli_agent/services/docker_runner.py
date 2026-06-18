from __future__ import annotations

import subprocess
import threading

from cli_agent.models import AppSettings, RunnerResult, RunPaths


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

    def run(self, run_paths: RunPaths, prompt: str) -> RunnerResult:
        acquired = self._worker_slots.acquire(timeout=self._settings.worker_queue_timeout_seconds)
        if not acquired:
            message = (
                "Worker capacity exceeded. "
                f"Already running {self._settings.max_concurrent_worker_runs} worker(s); "
                f"waited {self._settings.worker_queue_timeout_seconds:g} seconds for a slot."
            )
            _write_runner_logs(run_paths, "", message)
            return RunnerResult(exit_code=125, stdout="", stderr=message, capacity_exceeded=True)

        command = self.build_command(run_paths, prompt)
        try:
            try:
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=self._settings.worker_timeout_seconds,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                stdout = exc.stdout or ""
                stderr = exc.stderr or ""
                _write_runner_logs(run_paths, stdout, stderr)
                return RunnerResult(exit_code=124, stdout=stdout, stderr=stderr, timed_out=True)
            except OSError as exc:
                stderr = f"Could not start Docker worker: {exc}"
                _write_runner_logs(run_paths, "", stderr)
                return RunnerResult(exit_code=126, stdout="", stderr=stderr)

            _write_runner_logs(run_paths, completed.stdout, completed.stderr)
            return RunnerResult(
                exit_code=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
                timed_out=False,
            )
        finally:
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


def _write_runner_logs(run_paths: RunPaths, stdout: str, stderr: str) -> None:
    run_paths.logs_dir.mkdir(parents=True, exist_ok=True)
    (run_paths.logs_dir / "copilot.stdout.log").write_text(stdout, encoding="utf-8")
    (run_paths.logs_dir / "copilot.stderr.log").write_text(stderr, encoding="utf-8")
