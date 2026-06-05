from __future__ import annotations

from dci_poc.constants import API_TOOL_AUTO_ANALYSIS, API_TOOL_DCI_SEARCH


def build_tool_schemas(approved_source_paths: list[str], max_sources_per_run: int | None = None) -> list[dict]:
    if not approved_source_paths:
        raise ValueError("At least one approved source path is required")

    source_paths_schema: dict = {
        "type": "array",
        "items": {
            "type": "string",
            "enum": approved_source_paths,
            "description": "Exact path string from the approved source shortlist.",
        },
        "minItems": 1,
        "uniqueItems": True,
        "description": "Approved source paths to inspect.",
    }
    if max_sources_per_run is not None:
        source_paths_schema["maxItems"] = max_sources_per_run

    return [
        {
            "type": "function",
            "function": {
                "name": API_TOOL_DCI_SEARCH,
                "description": (
                    "Search approved raw local source files and return cited context only. "
                    "Use this when the user asks for source-backed lookup, not calculations. "
                    "If the user question is ambiguous, ask a chat clarification instead of calling this tool."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "question": {
                            "type": "string",
                            "description": "The user's search question, copied with enough context to answer.",
                        },
                        "source_paths": source_paths_schema,
                    },
                    "required": ["question", "source_paths"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": API_TOOL_AUTO_ANALYSIS,
                "description": (
                    "Retrieve required context from approved raw local source files, perform analysis or "
                    "calculation, and return a markdown report. Use only when the user supplied enough "
                    "inputs to run the analysis. Ask a chat clarification before calling this tool when "
                    "choices such as calculation method, scenario, table, row, or missing source scope are unclear."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "question": {
                            "type": "string",
                            "description": "The analysis question, including resolved user choices.",
                        },
                        "source_paths": source_paths_schema,
                        "analysis_goal": {
                            "type": "string",
                            "description": "Short statement of the calculation or analysis output expected.",
                        },
                    },
                    "required": ["question", "source_paths"],
                    "additionalProperties": False,
                },
            },
        },
    ]
