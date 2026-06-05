from __future__ import annotations

from dci_poc.constants import API_TOOL_AUTO_ANALYSIS, API_TOOL_DCI_SEARCH
from dci_poc.managers.tool_manager import ToolManager, detect_pre_run_clarification
from dci_poc.services.approved_sources import ApprovedSourceService
from dci_poc.services.artifact_service import ArtifactService
from dci_poc.services.prompt_service import WorkerPromptService
from dci_poc.services.run_folder_service import RunFolderService
from fakes import FakeRunner
from helpers import tool_call


def build_manager(app_config, runner: FakeRunner) -> ToolManager:
    return ToolManager(
        approved_sources=ApprovedSourceService(app_config),
        run_folders=RunFolderService(app_config),
        prompt_service=WorkerPromptService(),
        runner=runner,  # type: ignore[arg-type]
        artifact_service=ArtifactService(),
    )


def test_successful_dci_search_returns_report_with_citation(app_config) -> None:
    runner = FakeRunner("success")
    manager = build_manager(app_config, runner)

    envelope = manager.execute_tool_call(
        tool_call(
            API_TOOL_DCI_SEARCH,
            {
                "question": "Find paladin HP rules.",
                "source_paths": ["sample_sources/dnd5e_hp_reference.md"],
            },
        )
    )

    assert envelope.status.value == "success"
    assert envelope.report_markdown
    assert envelope.citation_summary == ["sample_sources/dnd5e_hp_reference.md"]
    assert len(runner.calls) == 1


def test_successful_auto_analysis_collects_csv_artifact(app_config) -> None:
    runner = FakeRunner("auto_analysis_success")
    manager = build_manager(app_config, runner)

    envelope = manager.execute_tool_call(
        tool_call(
            API_TOOL_AUTO_ANALYSIS,
            {
                "question": "Use fixed HP. Calculate HP for a level 11 dwarf paladin with 17 constitution.",
                "source_paths": ["sample_sources/dnd5e_hp_reference.md"],
            },
        )
    )

    assert envelope.status.value == "success"
    assert any(path.endswith("results.csv") for path in envelope.artifact_paths)
    assert len(runner.calls) == 1


def test_auto_analysis_ambiguous_hp_question_needs_clarification_before_runner(app_config) -> None:
    runner = FakeRunner("success")
    manager = build_manager(app_config, runner)

    envelope = manager.execute_tool_call(
        tool_call(
            API_TOOL_AUTO_ANALYSIS,
            {
                "question": "Calculate HP for a level 11 dwarf paladin with 17 constitution.",
                "source_paths": ["sample_sources/dnd5e_hp_reference.md"],
            },
        )
    )

    assert envelope.status.value == "needs_clarification"
    assert envelope.run_id is None
    assert envelope.needs_clarification is not None
    assert envelope.needs_clarification.missing_fields == ["hp_method"]
    assert runner.calls == []


def test_detect_pre_run_clarification_allows_resolved_hp_method() -> None:
    clarification = detect_pre_run_clarification(
        "Use fixed HP. Calculate HP for a level 11 dwarf paladin with 17 constitution."
    )

    assert clarification is None


def test_missing_answer_returns_error(app_config) -> None:
    manager = build_manager(app_config, FakeRunner("missing_answer"))

    envelope = manager.execute_tool_call(
        tool_call(
            API_TOOL_DCI_SEARCH,
            {
                "question": "Find context.",
                "source_paths": ["sample_sources/dnd5e_hp_reference.md"],
            },
        )
    )

    assert envelope.status.value == "error"
    assert "answer.md" in envelope.error


def test_raw_file_inspection_failure_returns_clear_error(app_config) -> None:
    manager = build_manager(app_config, FakeRunner("raw_file_failure"))

    envelope = manager.execute_tool_call(
        tool_call(
            API_TOOL_DCI_SEARCH,
            {
                "question": "Find context.",
                "source_paths": ["sample_sources/dnd5e_hp_reference.md"],
            },
        )
    )

    assert envelope.status.value == "error"
    assert "cannot inspect raw file" in envelope.error


def test_timeout_returns_timeout_status(app_config) -> None:
    manager = build_manager(app_config, FakeRunner("timeout"))

    envelope = manager.execute_tool_call(
        tool_call(
            API_TOOL_DCI_SEARCH,
            {
                "question": "Find context.",
                "source_paths": ["sample_sources/dnd5e_hp_reference.md"],
            },
        )
    )

    assert envelope.status.value == "timeout"


def test_nonzero_exit_returns_error(app_config) -> None:
    manager = build_manager(app_config, FakeRunner("nonzero"))

    envelope = manager.execute_tool_call(
        tool_call(
            API_TOOL_DCI_SEARCH,
            {
                "question": "Find context.",
                "source_paths": ["sample_sources/dnd5e_hp_reference.md"],
            },
        )
    )

    assert envelope.status.value == "error"
    assert "worker failed" in envelope.error
