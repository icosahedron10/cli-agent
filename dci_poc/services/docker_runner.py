from __future__ import annotations

import subprocess
import threading

from dci_poc.models import AppConfig, RunnerResult, RunPaths


class DockerRunner:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._worker_slots = threading.BoundedSemaphore(config.max_concurrent_worker_runs)

    def build_command(self, run_paths: RunPaths, prompt: str) -> list[str]:
        command = ["docker", "run", "--rm"]
        if self._config.docker_network:
            command.extend(["--network", self._config.docker_network])

        command.extend(_docker_env_args(self._config))
        command.extend(
            [
                "-v",
                f"{run_paths.root}:/workspace",
                "-w",
                "/workspace/work",
                self._config.worker_image,
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
        acquired = self._worker_slots.acquire(timeout=self._config.worker_queue_timeout_seconds)
        if not acquired:
            message = (
                "Worker capacity exceeded. "
                f"Already running {self._config.max_concurrent_worker_runs} worker(s); "
                f"waited {self._config.worker_queue_timeout_seconds:g} seconds for a slot."
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
                    timeout=self._config.worker_timeout_seconds,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                stdout = exc.stdout or ""
                stderr = exc.stderr or ""
                _write_runner_logs(run_paths, stdout, stderr)
                return RunnerResult(exit_code=124, stdout=stdout, stderr=stderr, timed_out=True)

            _write_runner_logs(run_paths, completed.stdout, completed.stderr)
            return RunnerResult(
                exit_code=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
                timed_out=False,
            )
        finally:
            self._worker_slots.release()


def _docker_env_args(config: AppConfig) -> list[str]:
    env = {
        "COPILOT_OFFLINE": "true" if config.copilot_offline else "false",
        "COPILOT_PROVIDER_BASE_URL": config.copilot_provider_base_url,
        "COPILOT_MODEL": config.copilot_model,
        "COPILOT_HOME": "/workspace/work/copilot-home",
        "COPILOT_CACHE_HOME": "/workspace/work/copilot-cache",
        "COPILOT_AUTO_UPDATE": "false",
        "COPILOT_OTEL_ENABLED": "false",
        "GITHUB_COPILOT_PROMPT_MODE_EXTENSIONS": "false",
        "GITHUB_COPILOT_PROMPT_MODE_REPO_HOOKS": "false",
    }
    if config.copilot_provider_api_key:
        env["COPILOT_PROVIDER_API_KEY"] = config.copilot_provider_api_key

    args: list[str] = []
    for name, value in env.items():
        args.extend(["-e", f"{name}={value}"])
    return args


def _write_runner_logs(run_paths: RunPaths, stdout: str, stderr: str) -> None:
    run_paths.logs_dir.mkdir(parents=True, exist_ok=True)
    (run_paths.logs_dir / "copilot.stdout.log").write_text(stdout, encoding="utf-8")
    (run_paths.logs_dir / "copilot.stderr.log").write_text(stderr, encoding="utf-8")
