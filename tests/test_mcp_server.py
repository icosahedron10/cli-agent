from __future__ import annotations

from typing import Any

import pytest

from cli_agent.constants import API_TOOL_AUTO_ANALYSIS, API_TOOL_SOURCE_SEARCH
from cli_agent.mcp_server import _mcp_tools_from_schemas, dispatch_tool_call
from cli_agent.models import ToolName
from cli_agent.schemas import build_tool_schemas
from cli_agent.services.approved_sources import ApprovedSourceService


class FakeSubagent:
    def __init__(self) -> None:
        self.calls: list[tuple[ToolName, dict[str, Any]]] = []

    def run_tool(self, tool_name: ToolName, args: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((tool_name, args))
        return {"status": "success", "tool_name": tool_name.value}


def tool_dump(tool) -> dict[str, Any]:
    if hasattr(tool, "model_dump"):
        return tool.model_dump(by_alias=True)
    return tool.dict(by_alias=True)


def test_mcp_tools_reuse_dynamic_input_schemas(app_settings) -> None:
    approved_sources = ApprovedSourceService(app_settings)
    schemas = build_tool_schemas(
        approved_sources.approved_paths(),
        max_sources_per_run=app_settings.max_sources_per_run,
    )

    tools = _mcp_tools_from_schemas(schemas)

    dumped_tools = {tool_dump(tool)["name"]: tool_dump(tool) for tool in tools}
    for schema in schemas:
        function = schema["function"]
        assert dumped_tools[function["name"]]["inputSchema"] == function["parameters"]


def test_mcp_tools_register_expected_names(app_settings) -> None:
    approved_sources = ApprovedSourceService(app_settings)
    schemas = build_tool_schemas(approved_sources.approved_paths())

    names = {tool_dump(tool)["name"] for tool in _mcp_tools_from_schemas(schemas)}

    assert names == {API_TOOL_SOURCE_SEARCH, API_TOOL_AUTO_ANALYSIS}


def test_dispatch_tool_call_invokes_subagent() -> None:
    subagent = FakeSubagent()
    args = {
        "question": "Find paladin HP rules.",
        "source_paths": ["sample_sources/dnd5e_hp_reference.md"],
    }

    result = dispatch_tool_call(subagent, API_TOOL_SOURCE_SEARCH, args)  # type: ignore[arg-type]

    assert result == {"status": "success", "tool_name": API_TOOL_SOURCE_SEARCH}
    assert subagent.calls == [(ToolName.SOURCE_SEARCH, args)]


def test_dispatch_tool_call_rejects_unknown_tool() -> None:
    with pytest.raises(ValueError, match="Unknown tool: missing_tool"):
        dispatch_tool_call(FakeSubagent(), "missing_tool", {})  # type: ignore[arg-type]


def test_dispatch_tool_call_rejects_non_object_arguments() -> None:
    with pytest.raises(ValueError, match="Tool arguments must be an object"):
        dispatch_tool_call(FakeSubagent(), API_TOOL_SOURCE_SEARCH, None)  # type: ignore[arg-type]
