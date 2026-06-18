from __future__ import annotations

import asyncio
import json
from typing import Any

import mcp.server.stdio
import mcp.types as types
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.models import InitializationOptions

from cli_agent.app_factory import build_subagent
from cli_agent.constants import API_TOOL_AUTO_ANALYSIS, API_TOOL_SOURCE_SEARCH
from cli_agent.models import AppSettings, ToolName
from cli_agent.schemas import build_tool_schemas
from cli_agent.services.approved_sources import ApprovedSourceService
from cli_agent.settings import load_app_settings
from cli_agent.subagent import Subagent


SERVER_NAME = "cli-agent"
SERVER_VERSION = "0.1.0"


def build_server(
    settings: AppSettings | None = None,
    approved_sources: ApprovedSourceService | None = None,
    subagent: Subagent | None = None,
) -> Server:
    app_settings = settings or load_app_settings()
    source_service = approved_sources or ApprovedSourceService(app_settings)
    tool_subagent = subagent or build_subagent(app_settings, source_service)
    tool_schemas = build_tool_schemas(
        source_service.approved_paths(),
        max_sources_per_run=app_settings.max_sources_per_run,
    )
    tools = _mcp_tools_from_schemas(tool_schemas)

    server = Server(SERVER_NAME)

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return tools

    @server.call_tool()
    async def call_tool(
        name: str,
        arguments: dict[str, Any],
    ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        result = dispatch_tool_call(tool_subagent, name, arguments)
        return [_tool_result_content(result)]

    return server


def _mcp_tools_from_schemas(tool_schemas: list[dict[str, Any]]) -> list[types.Tool]:
    return [_mcp_tool_from_schema(schema) for schema in tool_schemas]


def _mcp_tool_from_schema(schema: dict[str, Any]) -> types.Tool:
    function = schema.get("function")
    if not isinstance(function, dict):
        raise ValueError("Tool schema is missing function payload")

    name = function.get("name")
    description = function.get("description", "")
    parameters = function.get("parameters")
    if name not in {API_TOOL_SOURCE_SEARCH, API_TOOL_AUTO_ANALYSIS}:
        raise ValueError(f"Unknown tool schema: {name}")
    if not isinstance(description, str):
        raise ValueError(f"Tool schema {name} description must be a string")
    if not isinstance(parameters, dict):
        raise ValueError(f"Tool schema {name} parameters must be an object")

    return types.Tool(
        name=name,
        description=description,
        inputSchema=parameters,
    )


def _tool_result_content(result: dict[str, Any]) -> types.TextContent:
    return types.TextContent(type="text", text=json.dumps(result))


def dispatch_tool_call(subagent: Subagent, name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        raise ValueError("Tool arguments must be an object")
    try:
        tool_name = ToolName(name)
    except ValueError as exc:
        raise ValueError(f"Unknown tool: {name}") from exc
    return subagent.run_tool(tool_name, arguments)


async def run() -> None:
    server = build_server()
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name=SERVER_NAME,
                server_version=SERVER_VERSION,
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
