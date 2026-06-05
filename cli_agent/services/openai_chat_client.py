from __future__ import annotations

from typing import Any

import requests

from cli_agent.models import AppSettings


class OpenAIChatClient:
    def __init__(self, settings: AppSettings) -> None:
        self._settings = settings

    def create_chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._settings.chat_base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._settings.chat_api_key}",
            "Content-Type": "application/json",
        }
        response = requests.post(url, headers=headers, json=payload, timeout=self._settings.chat_timeout_seconds)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError("Chat completion endpoint returned a non-object JSON response")
        return data
