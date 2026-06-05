from __future__ import annotations

from dataclasses import replace
import json
import subprocess
from pathlib import Path

import pytest

from dci_poc.models import RunnerResult, ToolName
from dci_poc.services.approved_sources import ApprovedSourceService
from dci_poc.services.artifact_service import ArtifactService
from dci_poc.services.docker_runner import DockerRunner
from dci_poc.services.run_folder_service import RunFolderService


def test_run_folder_setup_and_source_copy(app_config) -> None:
    sources = ApprovedSourceService(app_config).all_sources()
    service = RunFolderService(app_config)

    run_paths = service.create_run_folder(ToolName.DCI_SEARCH)
    copied = service.copy_sources(run_paths, sources)

    assert run_paths.input_dir.exists()
    assert run_paths.work_dir.exists()
    assert run_paths.output_dir.exists()
    assert run_paths.logs_dir.exists()
    assert copied[0].relative_to(run_paths.input_dir).as_posix() == "sample_sources/dnd5e_hp_reference.md"


def test_artifact_service_writes_manifest_and_collects_artifacts(app_config) -> None:
    run_paths = RunFolderService(app_config).create_run_folder(ToolName.AUTO_ANALYSIS)
    sources = ApprovedSourceService(app_config).all_sources()
    (run_paths.output_dir / "answer.md").write_text(
        "Final result cites dnd5e_hp_reference.md.", encoding="utf-8"
    )
    (run_paths.output_dir / "results.csv").write_text("level,hp\n11,91\n", encoding="utf-8")

    envelope = ArtifactService().collect(
        run_paths,
        ToolName.AUTO_ANALYSIS,
        sources,
        RunnerResult(exit_code=0, stdout="", stderr=""),
        started_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    )

    assert envelope.status.value == "success"
    assert envelope.citation_summary == ["sample_sources/dnd5e_hp_reference.md"]
    assert any(path.endswith("results.csv") for path in envelope.artifact_paths)
    assert (run_paths.output_dir / "manifest.json").exists()
    manifest = json.loads((run_paths.output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_bytes"]["sample_sources/dnd5e_hp_reference.md"] > 0


def test_artifact_service_reports_missing_required_answer(app_config) -> None:
    run_paths = RunFolderService(app_config).create_run_folder(ToolName.DCI_SEARCH)
    sources = ApprovedSourceService(app_config).all_sources()

    envelope = ArtifactService().collect(
        run_paths,
        ToolName.DCI_SEARCH,
        sources,
        RunnerResult(exit_code=0, stdout="", stderr=""),
        started_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    )

    assert envelope.status.value == "error"
    assert "answer.md" in envelope.error


def test_artifact_service_reports_capacity_exceeded(app_config) -> None:
    run_paths = RunFolderService(app_config).create_run_folder(ToolName.DCI_SEARCH)
    sources = ApprovedSourceService(app_config).all_sources()

    envelope = ArtifactService().collect(
        run_paths,
        ToolName.DCI_SEARCH,
        sources,
        RunnerResult(exit_code=125, stdout="", stderr="worker slots full", capacity_exceeded=True),
        started_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    )

    assert envelope.status.value == "capacity_exceeded"
    assert envelope.error == "worker slots full"


def test_docker_runner_builds_command_with_env_and_mount(app_config) -> None:
    run_paths = RunFolderService(app_config).create_run_folder(ToolName.DCI_SEARCH)
    command = DockerRunner(app_config).build_command(run_paths, "hello")

    assert command[:3] == ["docker", "run", "--rm"]
    assert "-e" in command
    assert "COPILOT_OFFLINE=true" in command
    assert "COPILOT_PROVIDER_BASE_URL=http://host.docker.internal:11434" in command
    assert "COPILOT_MODEL=test-copilot-model" in command
    assert "COPILOT_OTEL_ENABLED=false" in command
    assert "COPILOT_ALLOW_ALL=true" not in command
    assert f"{run_paths.root}:/workspace" in command
    assert "--prompt" in command
    assert "hello" in command
    assert "--allow-all-tools" in command


def test_docker_runner_writes_logs_and_handles_nonzero(app_config, monkeypatch) -> None:
    run_paths = RunFolderService(app_config).create_run_folder(ToolName.DCI_SEARCH)

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 5, stdout="out", stderr="err")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = DockerRunner(app_config).run(run_paths, "prompt")

    assert result.exit_code == 5
    assert (run_paths.logs_dir / "copilot.stdout.log").read_text(encoding="utf-8") == "out"
    assert (run_paths.logs_dir / "copilot.stderr.log").read_text(encoding="utf-8") == "err"


def test_docker_runner_handles_timeout(app_config, monkeypatch) -> None:
    run_paths = RunFolderService(app_config).create_run_folder(ToolName.DCI_SEARCH)

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=1, output="partial", stderr="late")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = DockerRunner(app_config).run(run_paths, "prompt")

    assert result.timed_out is True
    assert result.exit_code == 124
    assert (run_paths.logs_dir / "copilot.stdout.log").read_text(encoding="utf-8") == "partial"


def test_docker_runner_rejects_when_capacity_is_full(app_config, monkeypatch) -> None:
    config = replace(
        app_config,
        max_concurrent_worker_runs=1,
        worker_queue_timeout_seconds=0.0,
    )
    run_paths = RunFolderService(config).create_run_folder(ToolName.DCI_SEARCH)
    runner = DockerRunner(config)
    spawned = False

    def fake_run(*args, **kwargs):
        nonlocal spawned
        spawned = True
        return subprocess.CompletedProcess(args[0], 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert runner._worker_slots.acquire(blocking=False)
    try:
        result = runner.run(run_paths, "prompt")
    finally:
        runner._worker_slots.release()

    assert result.capacity_exceeded is True
    assert result.exit_code == 125
    assert spawned is False
    assert "Worker capacity exceeded" in (run_paths.logs_dir / "copilot.stderr.log").read_text(encoding="utf-8")
