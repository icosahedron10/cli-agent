from __future__ import annotations

from cli_agent.managers.tool_manager import ToolManager
from cli_agent.services.approved_sources import ApprovedSourceService
from cli_agent.services.artifact_service import ArtifactService
from cli_agent.services.prompt_service import WorkerPromptService
from cli_agent.services.run_folder_service import RunFolderService
from cli_agent.subagent import Subagent
from fakes import FakeRunner


def build_subagent(app_settings, runner: FakeRunner) -> Subagent:
    manager = ToolManager(
        approved_sources=ApprovedSourceService(app_settings),
        run_folders=RunFolderService(app_settings),
        prompt_service=WorkerPromptService(),
        runner=runner,  # type: ignore[arg-type]
        artifact_service=ArtifactService(),
    )
    return Subagent(manager)


def test_source_search_returns_model_json(app_settings) -> None:
    subagent = build_subagent(app_settings, FakeRunner("success"))

    result = subagent.source_search(
        question="Find paladin HP rules.",
        source_paths=["sample_sources/dnd5e_hp_reference.md"],
    )

    assert result["status"] == "success"
    assert result["report_markdown"]
    assert result["citation_summary"] == ["sample_sources/dnd5e_hp_reference.md"]


def test_auto_analysis_returns_error_envelope_for_bad_source(app_settings) -> None:
    subagent = build_subagent(app_settings, FakeRunner("success"))

    result = subagent.auto_analysis(
        question="Use fixed HP. Calculate HP.",
        source_paths=["sample_sources/not-approved.md"],
        analysis_goal="Return the HP total.",
    )

    assert result["status"] == "error"
    assert result["error"] == "Unapproved source path requested: sample_sources/not-approved.md"
