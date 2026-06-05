from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cli_agent.constants import ANSWER_FILENAME, MANIFEST_FILENAME, NEEDS_CLARIFICATION_FILENAME
from cli_agent.models import (
    NeedsClarification,
    RunnerResult,
    SourceEntry,
    ToolEnvelope,
    ToolName,
    ToolStatus,
    RunPaths,
)


class ArtifactService:
    def collect(
        self,
        run_paths: RunPaths,
        tool_name: ToolName,
        sources: list[SourceEntry],
        runner_result: RunnerResult,
        started_at: datetime,
    ) -> ToolEnvelope:
        finished_at = datetime.now(timezone.utc)
        answer_path = run_paths.output_dir / ANSWER_FILENAME
        needs_path = run_paths.output_dir / NEEDS_CLARIFICATION_FILENAME
        report_markdown = _read_text_if_exists(answer_path)
        artifacts = _collect_optional_artifacts(run_paths.output_dir)

        if runner_result.capacity_exceeded:
            envelope = ToolEnvelope(
                status=ToolStatus.CAPACITY_EXCEEDED,
                run_id=run_paths.run_id,
                report_markdown=report_markdown,
                artifact_paths=_string_paths(artifacts),
                citation_summary=[],
                error=runner_result.stderr or "Worker capacity exceeded.",
            )
        elif runner_result.timed_out:
            envelope = ToolEnvelope(
                status=ToolStatus.TIMEOUT,
                run_id=run_paths.run_id,
                report_markdown=report_markdown,
                artifact_paths=_string_paths(artifacts),
                citation_summary=[],
                error="Worker timed out before completing.",
            )
        elif runner_result.exit_code != 0:
            envelope = ToolEnvelope(
                status=ToolStatus.ERROR,
                run_id=run_paths.run_id,
                report_markdown=report_markdown,
                artifact_paths=_string_paths(artifacts),
                citation_summary=[],
                error=_runner_error_message(runner_result),
            )
        elif needs_path.exists():
            needs_clarification = _load_needs_clarification(needs_path)
            envelope = ToolEnvelope(
                status=ToolStatus.NEEDS_CLARIFICATION,
                run_id=run_paths.run_id,
                report_markdown=report_markdown,
                artifact_paths=_string_paths(artifacts),
                citation_summary=_citation_summary(report_markdown, sources),
                needs_clarification=needs_clarification,
            )
        elif not answer_path.exists():
            envelope = ToolEnvelope(
                status=ToolStatus.ERROR,
                run_id=run_paths.run_id,
                report_markdown="",
                artifact_paths=_string_paths(artifacts),
                citation_summary=[],
                error="Worker completed but did not create output/answer.md.",
            )
        else:
            envelope = ToolEnvelope(
                status=ToolStatus.SUCCESS,
                run_id=run_paths.run_id,
                report_markdown=report_markdown,
                artifact_paths=_string_paths(artifacts),
                citation_summary=_citation_summary(report_markdown, sources),
            )

        _write_manifest(
            run_paths=run_paths,
            tool_name=tool_name,
            sources=sources,
            runner_result=runner_result,
            envelope=envelope,
            started_at=started_at,
            finished_at=finished_at,
        )
        return envelope


def _read_text_if_exists(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _collect_optional_artifacts(output_dir: Path) -> list[Path]:
    artifacts: list[Path] = []
    artifacts.extend(sorted(output_dir.glob("*.csv")))
    graphs_dir = output_dir / "graphs"
    if graphs_dir.exists():
        artifacts.extend(sorted(graphs_dir.glob("*.png")))
    return artifacts


def _string_paths(paths: list[Path]) -> list[str]:
    return [str(path.resolve()) for path in paths]


def _citation_summary(report_markdown: str, sources: list[SourceEntry]) -> list[str]:
    found: list[str] = []
    for source in sources:
        basename = Path(source.path).name
        if source.path in report_markdown or basename in report_markdown:
            found.append(source.path)
    return found


def _load_needs_clarification(path: Path) -> NeedsClarification:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} must contain valid JSON") from exc

    question = raw.get("question")
    missing_fields = raw.get("missing_fields", [])
    details = raw.get("details", {})
    if not isinstance(question, str) or not question.strip():
        raise ValueError("needs_clarification.json requires a non-empty question")
    if not isinstance(missing_fields, list) or not all(isinstance(item, str) for item in missing_fields):
        raise ValueError("needs_clarification.json missing_fields must be a list of strings")
    if not isinstance(details, dict):
        raise ValueError("needs_clarification.json details must be an object")

    return NeedsClarification(question=question, missing_fields=missing_fields, details=details)


def _runner_error_message(runner_result: RunnerResult) -> str:
    stderr = runner_result.stderr.strip()
    if stderr:
        return f"Worker exited with code {runner_result.exit_code}: {stderr}"
    return f"Worker exited with code {runner_result.exit_code}."


def _write_manifest(
    run_paths: RunPaths,
    tool_name: ToolName,
    sources: list[SourceEntry],
    runner_result: RunnerResult,
    envelope: ToolEnvelope,
    started_at: datetime,
    finished_at: datetime,
) -> None:
    manifest: dict[str, Any] = {
        "run_id": run_paths.run_id,
        "tool_name": tool_name.value,
        "status": envelope.status.value,
        "sources": [source.path for source in sources],
        "source_bytes": {source.path: source.size_bytes for source in sources},
        "artifacts": envelope.artifact_paths,
        "citation_summary": envelope.citation_summary,
        "runner_exit_code": runner_result.exit_code,
        "runner_timed_out": runner_result.timed_out,
        "runner_capacity_exceeded": runner_result.capacity_exceeded,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
    }
    if envelope.error:
        manifest["error"] = envelope.error
    if envelope.needs_clarification:
        manifest["needs_clarification"] = {
            "question": envelope.needs_clarification.question,
            "missing_fields": envelope.needs_clarification.missing_fields,
            "details": envelope.needs_clarification.details,
        }

    manifest_path = run_paths.output_dir / MANIFEST_FILENAME
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
