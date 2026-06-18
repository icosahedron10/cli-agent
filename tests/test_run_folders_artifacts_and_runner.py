from __future__ import annotations

from dataclasses import replace
import json
import subprocess
from pathlib import Path

import pytest

from cli_agent.models import RunnerResult, ToolName, WorkerRunSpec
from cli_agent.services.approved_sources import ApprovedSourceService
from cli_agent.services.artifact_service import ArtifactService
from cli_agent.services.docker_runner import DockerRunner
from cli_agent.services.prompt_service import WorkerPromptService
from cli_agent.services.run_folder_service import RunFolderService


def test_run_folder_setup_and_source_copy(app_settings) -> None:
    sources = ApprovedSourceService(app_settings).all_sources()
    service = RunFolderService(app_settings)

    run_paths = service.create_run_folder(ToolName.SOURCE_SEARCH)
    copied = service.copy_sources(run_paths, sources)

    assert run_paths.input_dir.exists()
    assert run_paths.work_dir.exists()
    assert run_paths.output_dir.exists()
    assert run_paths.logs_dir.exists()
    assert copied[0].relative_to(run_paths.input_dir).as_posix() == "sample_sources/dnd5e_hp_reference.md"


def test_run_folder_prepares_pdf_text_for_worker(app_settings, monkeypatch) -> None:
    source_path = app_settings.repo_root / "docs" / "rules.pdf"
    source_path.parent.mkdir()
    source_path.write_bytes(b"%PDF-1.7\n")
    settings_path = app_settings.repo_root / "pdf_sources.json"
    settings_path.write_text(
        json.dumps(
            {
                "sources": [
                    {"path": "docs/rules.pdf", "label": "Rules PDF", "description": ""}
                ]
            }
        ),
        encoding="utf-8",
    )
    settings = replace(app_settings, approved_sources_path=settings_path)
    sources = ApprovedSourceService(settings).all_sources()
    run_paths = RunFolderService(settings).create_run_folder(ToolName.SOURCE_SEARCH)

    def fake_extract_pdf_text(pdf_path: Path) -> Path:
        text_path = pdf_path.with_suffix(pdf_path.suffix + ".txt")
        text_path.write_text("--- Page 1 ---\nRules text.", encoding="utf-8")
        return text_path

    monkeypatch.setattr("cli_agent.services.run_folder_service._extract_pdf_text", fake_extract_pdf_text)
    prepared = RunFolderService(settings).copy_sources(run_paths, sources)
    prompt = WorkerPromptService().build_prompt(
        WorkerRunSpec(
            tool_name=ToolName.SOURCE_SEARCH,
            question="Find rules text.",
            source_entries=sources,
            run_paths=run_paths,
        ),
        prepared,
    )

    assert (run_paths.input_dir / "docs" / "rules.pdf").exists()
    assert prepared[0].relative_to(run_paths.input_dir).as_posix() == "docs/rules.pdf.txt"
    assert "extracted text with page markers" in prompt
    assert "/workspace/input/docs/rules.pdf.txt" in prompt


def test_artifact_service_writes_manifest_and_collects_artifacts(app_settings) -> None:
    run_paths = RunFolderService(app_settings).create_run_folder(ToolName.AUTO_ANALYSIS)
    sources = ApprovedSourceService(app_settings).all_sources()
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


def test_artifact_service_reports_missing_required_answer(app_settings) -> None:
    run_paths = RunFolderService(app_settings).create_run_folder(ToolName.SOURCE_SEARCH)
    sources = ApprovedSourceService(app_settings).all_sources()

    envelope = ArtifactService().collect(
        run_paths,
        ToolName.SOURCE_SEARCH,
        sources,
        RunnerResult(exit_code=0, stdout="", stderr=""),
        started_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    )

    assert envelope.status.value == "error"
    assert "answer.md" in envelope.error


def test_artifact_service_reports_capacity_exceeded(app_settings) -> None:
    run_paths = RunFolderService(app_settings).create_run_folder(ToolName.SOURCE_SEARCH)
    sources = ApprovedSourceService(app_settings).all_sources()

    envelope = ArtifactService().collect(
        run_paths,
        ToolName.SOURCE_SEARCH,
        sources,
        RunnerResult(exit_code=125, stdout="", stderr="worker slots full", capacity_exceeded=True),
        started_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    )

    assert envelope.status.value == "capacity_exceeded"
    assert envelope.error == "worker slots full"


def test_docker_runner_builds_command_with_env_and_mount(app_settings) -> None:
    run_paths = RunFolderService(app_settings).create_run_folder(ToolName.SOURCE_SEARCH)
    command = DockerRunner(app_settings).build_command(run_paths, "hello")

    assert command[:3] == ["docker", "run", "--rm"]
    assert "--init" in command
    assert "--cap-drop=ALL" in command
    assert "--security-opt=no-new-privileges" in command
    assert "--read-only" in command
    assert "--tmpfs" in command
    assert "/tmp:rw,nosuid,nodev,size=64m" in command
    assert "--pids-limit=256" in command
    assert "--network" not in command
    assert "-e" in command
    assert "COPILOT_OFFLINE=true" in command
    assert "COPILOT_PROVIDER_BASE_URL=http://host.docker.internal:8000/v1" in command
    assert "COPILOT_MODEL=test-copilot-model" in command
    assert "HOME=/workspace/work/home" in command
    assert "XDG_CACHE_HOME=/workspace/work/cache" in command
    assert "XDG_CONFIG_HOME=/workspace/work/config" in command
    assert "COPILOT_OTEL_ENABLED=false" in command
    assert "COPILOT_ALLOW_ALL=true" not in command
    assert f"{run_paths.root}:/workspace" in command
    assert "--prompt" in command
    assert "hello" in command
    assert "--allow-all-tools" in command


def test_docker_runner_uses_configured_network(app_settings) -> None:
    settings = replace(app_settings, docker_network="cli-agent-firewalled")
    run_paths = RunFolderService(settings).create_run_folder(ToolName.SOURCE_SEARCH)
    command = DockerRunner(settings).build_command(run_paths, "hello")

    assert command[:3] == ["docker", "run", "--rm"]
    network_index = command.index("--network")
    assert command[network_index : network_index + 2] == ["--network", "cli-agent-firewalled"]


def test_docker_runner_writes_logs_and_handles_nonzero(app_settings, monkeypatch) -> None:
    run_paths = RunFolderService(app_settings).create_run_folder(ToolName.SOURCE_SEARCH)

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 5, stdout="out", stderr="err")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = DockerRunner(app_settings).run(run_paths, "prompt")

    assert result.exit_code == 5
    assert (run_paths.logs_dir / "copilot.stdout.log").read_text(encoding="utf-8") == "out"
    assert (run_paths.logs_dir / "copilot.stderr.log").read_text(encoding="utf-8") == "err"


def test_docker_runner_handles_timeout(app_settings, monkeypatch) -> None:
    run_paths = RunFolderService(app_settings).create_run_folder(ToolName.SOURCE_SEARCH)

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=1, output="partial", stderr="late")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = DockerRunner(app_settings).run(run_paths, "prompt")

    assert result.timed_out is True
    assert result.exit_code == 124
    assert (run_paths.logs_dir / "copilot.stdout.log").read_text(encoding="utf-8") == "partial"


def test_docker_runner_handles_startup_failure(app_settings, monkeypatch) -> None:
    run_paths = RunFolderService(app_settings).create_run_folder(ToolName.SOURCE_SEARCH)

    def fake_run(*args, **kwargs):
        raise FileNotFoundError("docker")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = DockerRunner(app_settings).run(run_paths, "prompt")

    assert result.exit_code == 126
    assert "Could not start Docker worker" in result.stderr
    assert "Could not start Docker worker" in (run_paths.logs_dir / "copilot.stderr.log").read_text(
        encoding="utf-8"
    )


def test_docker_runner_rejects_when_capacity_is_full(app_settings, monkeypatch) -> None:
    settings = replace(
        app_settings,
        max_concurrent_worker_runs=1,
        worker_queue_timeout_seconds=0.0,
    )
    run_paths = RunFolderService(settings).create_run_folder(ToolName.SOURCE_SEARCH)
    runner = DockerRunner(settings)
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
