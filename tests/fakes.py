from __future__ import annotations

from pathlib import Path
from typing import Any

from cli_agent.models import RunnerResult, RunPaths


class FakeChatClient:
    def __init__(self, messages: list[dict[str, Any]]) -> None:
        self._messages = messages
        self.payloads: list[dict[str, Any]] = []

    def create_chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.payloads.append(payload)
        if not self._messages:
            raise AssertionError("No fake chat messages remain")
        return {"choices": [{"message": self._messages.pop(0)}]}


class FakeRunner:
    def __init__(self, mode: str = "success", answer: str | None = None) -> None:
        self.mode = mode
        self.answer = answer or "Answer with citation (dnd5e_hp_reference.md: Section Paladin)."
        self.calls: list[tuple[RunPaths, str]] = []

    def run(self, run_paths: RunPaths, prompt: str) -> RunnerResult:
        self.calls.append((run_paths, prompt))
        if self.mode == "success":
            (run_paths.output_dir / "answer.md").write_text(self.answer, encoding="utf-8")
            return RunnerResult(exit_code=0, stdout="ok", stderr="")
        if self.mode == "auto_analysis_success":
            (run_paths.output_dir / "answer.md").write_text(self.answer, encoding="utf-8")
            (run_paths.output_dir / "results.csv").write_text("level,hp\n11,91\n", encoding="utf-8")
            return RunnerResult(exit_code=0, stdout="ok", stderr="")
        if self.mode == "needs_clarification":
            (run_paths.output_dir / "answer.md").write_text("Need more info.", encoding="utf-8")
            (run_paths.output_dir / "needs_clarification.json").write_text(
                '{"question":"Fixed or rolled?","missing_fields":["hp_method"],"details":{}}',
                encoding="utf-8",
            )
            return RunnerResult(exit_code=0, stdout="ok", stderr="")
        if self.mode == "missing_answer":
            return RunnerResult(exit_code=0, stdout="ok", stderr="")
        if self.mode == "raw_file_failure":
            return RunnerResult(exit_code=2, stdout="", stderr="cannot inspect raw file")
        if self.mode == "timeout":
            return RunnerResult(exit_code=124, stdout="", stderr="timed out", timed_out=True)
        if self.mode == "nonzero":
            return RunnerResult(exit_code=3, stdout="", stderr="worker failed")
        raise AssertionError(f"Unknown fake runner mode: {self.mode}")


def list_files(root: Path) -> list[str]:
    return sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.is_file())
