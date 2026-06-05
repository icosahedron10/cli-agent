from __future__ import annotations

from typing import Any

import requests

from dci_poc.models import AppConfig


class OpenAIChatClient:
    def __init__(self, config: AppConfig) -> None:
        self._config = config

    def create_chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._config.chat_base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._config.chat_api_key}",
            "Content-Type": "application/json",
        }
        response = requests.post(url, headers=headers, json=payload, timeout=self._config.chat_timeout_seconds)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError("Chat completion endpoint returned a non-object JSON response")
        return data
