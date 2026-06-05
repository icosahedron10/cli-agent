from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from dci_poc.constants import API_TOOL_AUTO_ANALYSIS, API_TOOL_DCI_SEARCH
from dci_poc.exceptions import ApprovedSourceError, ToolDispatchError
from dci_poc.models import (
    NeedsClarification,
    RunnerResult,
    ToolEnvelope,
    ToolName,
    ToolStatus,
    WorkerRunSpec,
)
from dci_poc.services.approved_sources import ApprovedSourceService
from dci_poc.services.artifact_service import ArtifactService
from dci_poc.services.docker_runner import DockerRunner
from dci_poc.services.prompt_service import WorkerPromptService
from dci_poc.services.run_folder_service import RunFolderService


class ToolManager:
    def __init__(
        self,
        approved_sources: ApprovedSourceService,
        run_folders: RunFolderService,
        prompt_service: WorkerPromptService,
        runner: DockerRunner,
        artifact_service: ArtifactService,
    ) -> None:
        self._approved_sources = approved_sources
        self._run_folders = run_folders
        self._prompt_service = prompt_service
        self._runner = runner
        self._artifact_service = artifact_service

    def tool_safety_error(self, message: str) -> ToolEnvelope:
        return ToolEnvelope(
            status=ToolStatus.ERROR,
            run_id=None,
            report_markdown="",
            artifact_paths=[],
            citation_summary=[],
            error=message,
        )

    def execute_tool_call(self, tool_call: dict[str, Any]) -> ToolEnvelope:
        try:
            tool_name, args = _parse_tool_call(tool_call)
            question = _required_string(args, "question")
            sources = self._approved_sources.validate_requested_paths(args.get("source_paths"))

            if tool_name is ToolName.AUTO_ANALYSIS:
                clarification = detect_pre_run_clarification(question)
                if clarification is not None:
                    return ToolEnvelope(
                        status=ToolStatus.NEEDS_CLARIFICATION,
                        run_id=None,
                        report_markdown="",
                        artifact_paths=[],
                        citation_summary=[],
                        needs_clarification=clarification,
                    )

            run_paths = self._run_folders.create_run_folder(tool_name)
            copied_paths = self._run_folders.copy_sources(run_paths, sources)
            spec = WorkerRunSpec(
                tool_name=tool_name,
                question=question,
                source_entries=sources,
                run_paths=run_paths,
            )
            prompt = self._prompt_service.build_prompt(spec, copied_paths)
            started_at = datetime.now(timezone.utc)
            runner_result = self._runner.run(run_paths, prompt)
            return self._artifact_service.collect(run_paths, tool_name, sources, runner_result, started_at)
        except (ApprovedSourceError, ToolDispatchError, ValueError) as exc:
            return self.tool_safety_error(str(exc))


def _parse_tool_call(tool_call: dict[str, Any]) -> tuple[ToolName, dict[str, Any]]:
    function = tool_call.get("function")
    if not isinstance(function, dict):
        raise ToolDispatchError("Tool call is missing function payload")

    name = function.get("name")
    if name not in {API_TOOL_DCI_SEARCH, API_TOOL_AUTO_ANALYSIS}:
        raise ToolDispatchError(f"Unknown tool requested: {name}")

    raw_arguments = function.get("arguments", "{}")
    if not isinstance(raw_arguments, str):
        raise ToolDispatchError("Tool call arguments must be a JSON string")
    try:
        args = json.loads(raw_arguments)
    except json.JSONDecodeError as exc:
        raise ToolDispatchError("Tool call arguments must be valid JSON") from exc
    if not isinstance(args, dict):
        raise ToolDispatchError("Tool call arguments must decode to an object")

    return ToolName(name), args


def _required_string(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ToolDispatchError(f"{key} must be a non-empty string")
    return value.strip()


def detect_pre_run_clarification(question: str) -> NeedsClarification | None:
    normalized = question.lower()
    is_hp_question = "hp" in normalized or "hit point" in normalized or "hit points" in normalized
    has_level = "level" in normalized
    has_con = "constitution" in normalized or " con " in f" {normalized} "
    mentions_method = any(term in normalized for term in ["fixed", "average", "rolled", "rolls", "max at each"])

    if is_hp_question and has_level and has_con and not mentions_method:
        return NeedsClarification(
            question=(
                "Should the HP calculation use fixed/average HP after level 1, or rolled HP? "
                "If rolled, provide each level-up roll. Also specify any ancestry, feat, or table option "
                "that adds hit points."
            ),
            missing_fields=["hp_method"],
            details={"reason": "HP after level 1 depends on fixed versus rolled hit point choices."},
        )
    return None


def result_as_tool_message(tool_call_id: str, envelope: ToolEnvelope) -> dict[str, Any]:
    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "content": json.dumps(envelope.to_model_json(), separators=(",", ":")),
    }

