from __future__ import annotations

import pytest

from cli_agent.exceptions import SettingsError
from cli_agent.settings import load_app_settings


def test_load_app_settings_uses_v1_worker_provider_default(tmp_path) -> None:
    settings = load_app_settings(tmp_path)

    assert settings.chat_base_url == "http://localhost:8000/v1"
    assert settings.chat_model == "Qwen3.6-27B"
    assert settings.copilot_provider_base_url == "http://host.docker.internal:8000/v1"
    assert settings.copilot_model == settings.chat_model


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ("1", True),
        ("true", True),
        ("YES", True),
        ("on", True),
        ("0", False),
        ("false", False),
        ("No", False),
        ("off", False),
    ],
)
def test_load_app_settings_parses_bool_env_values(monkeypatch, tmp_path, raw_value, expected) -> None:
    monkeypatch.setenv("COPILOT_OFFLINE", raw_value)

    settings = load_app_settings(tmp_path)

    assert settings.copilot_offline is expected


def test_load_app_settings_rejects_invalid_bool_env(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("COPILOT_OFFLINE", "maybe")

    with pytest.raises(SettingsError, match="COPILOT_OFFLINE must be one of"):
        load_app_settings(tmp_path)
