from __future__ import annotations

from typing import Any, Protocol

from dci_poc.models import AppConfig


class ChatClient(Protocol):
    def create_chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        ...


class ChatCompletionAgent:
    def __init__(self, config: AppConfig, chat_client: ChatClient) -> None:
        self._config = config
        self._chat_client = chat_client

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        tool_choice: str | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self._config.chat_model,
            "messages": messages,
            "temperature": self._config.chat_temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice or "auto"
            payload["parallel_tool_calls"] = False

        response = self._chat_client.create_chat_completion(payload)
        choices = response.get("choices")
        if not isinstance(choices, list) or not choices:
            raise RuntimeError("Chat completion response did not include choices")

        message = choices[0].get("message")
        if not isinstance(message, dict):
            raise RuntimeError("Chat completion response did not include a message")
        return message

