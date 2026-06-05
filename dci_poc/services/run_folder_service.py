from __future__ import annotations

import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dci_poc.models import AppConfig, RunPaths, SourceEntry, ToolName


class RunFolderService:
    def __init__(self, config: AppConfig) -> None:
        self._config = config

    def create_run_folder(self, tool_name: ToolName) -> RunPaths:
        run_id = _new_run_id(tool_name)
        root = self._config.runs_root / run_id
        input_dir = root / "input"
        work_dir = root / "work"
        output_dir = root / "output"
        logs_dir = output_dir / "logs"

        for directory in (input_dir, work_dir, output_dir, logs_dir):
            directory.mkdir(parents=True, exist_ok=False)

        return RunPaths(
            run_id=run_id,
            root=root,
            input_dir=input_dir,
            work_dir=work_dir,
            output_dir=output_dir,
            logs_dir=logs_dir,
        )

    def copy_sources(self, run_paths: RunPaths, sources: list[SourceEntry]) -> list[Path]:
        copied: list[Path] = []
        for source in sources:
            destination = run_paths.input_dir / Path(source.path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source.absolute_path, destination)
            copied.append(destination)
        return copied


def _new_run_id(tool_name: ToolName) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{tool_name.value}-{uuid.uuid4().hex[:8]}"

