from __future__ import annotations

from pathlib import Path

from cli_agent.models import WorkerRunSpec


class WorkerPromptService:
    def build_prompt(self, spec: WorkerRunSpec, prepared_input_paths: list[Path]) -> str:
        source_lines = []
        for entry, prepared_path in zip(spec.source_entries, prepared_input_paths, strict=True):
            container_path = _container_path(prepared_path, spec.run_paths.root)
            source_lines.append(_source_line(entry.path, entry.label, container_path, prepared_path))

        instructions = _tool_instructions(spec)
        return "\n".join(
            [
                "You are a short-lived CLI analysis worker running inside a restricted Docker container.",
                "Read only the raw files listed below. Do not use network sources.",
                "Write all outputs under /workspace/output.",
                "Use /workspace/work for temporary files and calculations.",
                "Use Python from the shell when calculation, CSV creation, or plotting is useful.",
                "If a raw input file cannot be inspected, fail clearly and do not invent evidence.",
                "",
                "Approved input files:",
                *source_lines,
                "",
                instructions,
                "",
                "Required output contract:",
                "- Create /workspace/output/answer.md.",
                "- If ambiguity prevents a reliable answer, create /workspace/output/needs_clarification.json ",
                '  with {"question": "...", "missing_fields": ["..."], "details": {...}}.',
                "- Create optional CSV files directly under /workspace/output when useful.",
                "- Create optional PNG graphs under /workspace/output/graphs when useful.",
                "",
                "User question:",
                spec.question,
            ]
        )


def _tool_instructions(spec: WorkerRunSpec) -> str:
    if spec.tool_name.value == "source_search":
        return "\n".join(
            [
                "Mode: source_search.",
                "Produce cited context only.",
                "Use concise excerpts or paraphrases backed by citations.",
                "Every substantive bullet must cite filename plus line, section, row, or page when available.",
                "Do not perform calculations beyond locating and explaining relevant source context.",
            ]
        )

    return "\n".join(
        [
            "Mode: auto_analysis.",
            "Produce a markdown report with assumptions, citations, calculation steps, and final result.",
            "Cite filename plus line, section, row, or page when available for all source-backed facts.",
            "Include CSV or PNG artifacts only when they make the analysis easier to inspect.",
        ]
    )


def _container_path(path: Path, run_root: Path) -> str:
    relative = path.resolve().relative_to(run_root.resolve())
    return "/workspace/" + relative.as_posix()


def _source_line(source_path: str, label: str, container_path: str, prepared_path: Path) -> str:
    if source_path.lower().endswith(".pdf") and prepared_path.name.lower().endswith(".pdf.txt"):
        return f"- {source_path}: {container_path} ({label}; extracted text with page markers)"
    return f"- {source_path}: {container_path} ({label})"
