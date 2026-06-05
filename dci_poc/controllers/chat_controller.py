from __future__ import annotations

import json
from typing import Any

from dci_poc.agents.chat_agent import ChatCompletionAgent
from dci_poc.managers.tool_manager import ToolManager, result_as_tool_message
from dci_poc.models import ChatTurnResult, ToolEnvelope


SYSTEM_MESSAGE = {
    "role": "system",
    "content": (
        "You are a DCI source analysis assistant. You may use dci_search for cited source lookup "
        "and auto_analysis for calculations or analysis. The UI labels are dci-search and auto-analysis. "
        "Ask a concise clarification before using a tool when the user has not supplied enough choices "
        "to make the run reliable. Use at most one tool call per user turn."
    ),
}


class ChatController:
    def __init__(
        self,
        agent: ChatCompletionAgent,
        tool_manager: ToolManager,
        tool_schemas: list[dict[str, Any]],
    ) -> None:
        self._agent = agent
        self._tool_manager = tool_manager
        self._tool_schemas = tool_schemas

    def handle_user_turn(self, history: list[dict[str, Any]], user_content: str) -> ChatTurnResult:
        messages = _ensure_system_message(history)
        messages.append({"role": "user", "content": user_content})

        assistant_message = self._agent.complete(messages, self._tool_schemas, "auto")
        tool_calls = assistant_message.get("tool_calls") or []
        if not tool_calls:
            messages.append(assistant_message)
            return ChatTurnResult(messages=messages, assistant_message=assistant_message)

        messages.append(assistant_message)
        envelopes = self._execute_or_reject_tool_calls(tool_calls)
        for tool_call, envelope in zip(tool_calls, envelopes, strict=True):
            tool_call_id = _required_tool_call_id(tool_call)
            messages.append(result_as_tool_message(tool_call_id, envelope))

        final_message = self._agent.complete(messages, None, None)
        messages.append(final_message)
        return ChatTurnResult(messages=messages, assistant_message=final_message, tool_envelopes=envelopes)

    def _execute_or_reject_tool_calls(self, tool_calls: list[dict[str, Any]]) -> list[ToolEnvelope]:
        if len(tool_calls) == 1:
            return [self._tool_manager.execute_tool_call(tool_calls[0])]

        envelope = self._tool_manager.tool_safety_error(
            f"Rejected {len(tool_calls)} tool calls. Only one tool call is allowed per user turn."
        )
        return [envelope for _ in tool_calls]


def _ensure_system_message(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if history and history[0].get("role") == "system":
        return [dict(message) for message in history]
    return [SYSTEM_MESSAGE, *[dict(message) for message in history]]


def _required_tool_call_id(tool_call: dict[str, Any]) -> str:
    tool_call_id = tool_call.get("id")
    if not isinstance(tool_call_id, str) or not tool_call_id:
        raise RuntimeError("Tool call is missing a valid id")
    return tool_call_id


def visible_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    visible: list[dict[str, Any]] = []
    for message in messages:
        if message.get("role") not in {"user", "assistant"}:
            continue
        if message.get("role") == "assistant" and message.get("tool_calls") and not message.get("content"):
            continue
        visible.append(message)
    return visible


def decode_tool_message_content(message: dict[str, Any]) -> dict[str, Any] | None:
    if message.get("role") != "tool":
        return None
    content = message.get("content")
    if not isinstance(content, str):
        return None
    try:
        decoded = json.loads(content)
    except json.JSONDecodeError:
        return None
    return decoded if isinstance(decoded, dict) else None
