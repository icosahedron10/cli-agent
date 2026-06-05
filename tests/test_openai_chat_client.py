from __future__ import annotations

from dataclasses import replace
from typing import Any

from cli_agent.services.openai_chat_client import OpenAIChatClient


class FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


def test_openai_chat_client_uses_settingsured_timeout(app_settings, monkeypatch) -> None:
    settings = replace(app_settings, chat_timeout_seconds=12.5)
    seen: dict[str, Any] = {}

    def fake_post(*args, **kwargs):
        seen["timeout"] = kwargs["timeout"]
        return FakeResponse({"choices": [{"message": {"role": "assistant", "content": "ok"}}]})

    monkeypatch.setattr("cli_agent.services.openai_chat_client.requests.post", fake_post)

    data = OpenAIChatClient(settings).create_chat_completion({"messages": []})

    assert seen["timeout"] == 12.5
    assert data["choices"][0]["message"]["content"] == "ok"
