from __future__ import annotations

import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from cli_agent.exceptions import ToolDispatchError
from cli_agent.models import AppSettings, RunPaths, SourceEntry, ToolName


class RunFolderService:
    def __init__(self, settings: AppSettings) -> None:
        self._settings = settings

    def create_run_folder(self, tool_name: ToolName) -> RunPaths:
        run_id = _new_run_id(tool_name)
        root = self._settings.runs_root / run_id
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
        prepared: list[Path] = []
        for source in sources:
            destination = run_paths.input_dir / Path(source.path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source.absolute_path, destination)
            prepared.append(_prepare_worker_input(destination))
        return prepared


def _new_run_id(tool_name: ToolName) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{tool_name.value}-{uuid.uuid4().hex[:8]}"


def _prepare_worker_input(copied_source: Path) -> Path:
    if copied_source.suffix.lower() != ".pdf":
        return copied_source
    return _extract_pdf_text(copied_source)


def _extract_pdf_text(pdf_path: Path) -> Path:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ToolDispatchError(
            "PDF source requested, but pypdf is not installed. Run `poetry install` before using PDFs."
        ) from exc

    try:
        reader = PdfReader(str(pdf_path))
        page_blocks: list[str] = []
        found_text = False
        for index, page in enumerate(reader.pages, start=1):
            page_text = page.extract_text() or ""
            if page_text.strip():
                found_text = True
            page_blocks.append(f"--- Page {index} ---\n{page_text.strip()}")
    except Exception as exc:
        raise ToolDispatchError(f"Could not extract text from PDF source {pdf_path.name}: {exc}") from exc

    if not found_text:
        raise ToolDispatchError(f"PDF source has no extractable text: {pdf_path.name}")

    text_path = pdf_path.with_suffix(pdf_path.suffix + ".txt")
    text_path.write_text(
        f"# Extracted text from {pdf_path.name}\n\n" + "\n\n".join(page_blocks) + "\n",
        encoding="utf-8",
    )
    return text_path
