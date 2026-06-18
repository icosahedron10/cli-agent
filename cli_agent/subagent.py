from __future__ import annotations

from typing import Any

from cli_agent.managers.tool_manager import ToolManager
from cli_agent.models import ToolName


class Subagent:
    def __init__(self, tool_manager: ToolManager) -> None:
        self._tool_manager = tool_manager

    def source_search(self, question: str, source_paths: list[str]) -> dict[str, Any]:
        envelope = self._tool_manager.run_tool(
            ToolName.SOURCE_SEARCH,
            {
                "question": question,
                "source_paths": source_paths,
            },
        )
        return envelope.to_model_json()

    def auto_analysis(
        self,
        question: str,
        source_paths: list[str],
        analysis_goal: str | None = None,
    ) -> dict[str, Any]:
        args: dict[str, Any] = {
            "question": question,
            "source_paths": source_paths,
        }
        if analysis_goal is not None:
            args["analysis_goal"] = analysis_goal

        envelope = self._tool_manager.run_tool(ToolName.AUTO_ANALYSIS, args)
        return envelope.to_model_json()
