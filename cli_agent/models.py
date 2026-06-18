from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class ToolName(str, Enum):
    SOURCE_SEARCH = "source_search"
    AUTO_ANALYSIS = "auto_analysis"


class ToolStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    NEEDS_CLARIFICATION = "needs_clarification"
    TIMEOUT = "timeout"
    CAPACITY_EXCEEDED = "capacity_exceeded"


@dataclass(frozen=True)
class SourceEntry:
    path: str
    label: str
    description: str
    absolute_path: Path
    size_bytes: int


@dataclass(frozen=True)
class AppSettings:
    repo_root: Path
    approved_sources_path: Path
    runs_root: Path
    chat_base_url: str
    chat_api_key: str
    chat_model: str
    chat_temperature: float
    chat_timeout_seconds: float
    max_api_jobs: int
    worker_image: str
    worker_timeout_seconds: int
    worker_queue_timeout_seconds: float
    max_concurrent_worker_runs: int
    max_sources_per_run: int
    max_source_bytes: int
    max_total_source_bytes_per_run: int
    copilot_provider_base_url: str
    copilot_model: str
    copilot_provider_api_key: str | None = None
    copilot_offline: bool = True
    docker_network: str | None = None


@dataclass(frozen=True)
class RunPaths:
    run_id: str
    root: Path
    input_dir: Path
    work_dir: Path
    output_dir: Path
    logs_dir: Path


@dataclass(frozen=True)
class WorkerRunSpec:
    tool_name: ToolName
    question: str
    source_entries: list[SourceEntry]
    run_paths: RunPaths
    analysis_goal: str | None = None


@dataclass(frozen=True)
class RunnerResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False
    capacity_exceeded: bool = False


@dataclass(frozen=True)
class Artifact:
    kind: str
    path: Path


@dataclass(frozen=True)
class NeedsClarification:
    question: str
    missing_fields: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolEnvelope:
    status: ToolStatus
    run_id: str | None
    report_markdown: str
    artifact_paths: list[str]
    citation_summary: list[str]
    trace_paths: list[str] = field(default_factory=list)
    needs_clarification: NeedsClarification | None = None
    error: str | None = None

    def to_model_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": self.status.value,
            "run_id": self.run_id,
            "report_markdown": self.report_markdown,
            "artifact_paths": self.artifact_paths,
            "citation_summary": self.citation_summary,
            "trace_paths": self.trace_paths,
        }
        if self.needs_clarification is not None:
            payload["needs_clarification"] = {
                "question": self.needs_clarification.question,
                "missing_fields": self.needs_clarification.missing_fields,
                "details": self.needs_clarification.details,
            }
        if self.error:
            payload["error"] = self.error
        return payload


@dataclass(frozen=True)
class ChatTurnResult:
    messages: list[dict[str, Any]]
    assistant_message: dict[str, Any]
    tool_envelopes: list[ToolEnvelope] = field(default_factory=list)
