from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import json

import pytest

from cli_agent.models import AppSettings


@pytest.fixture
def app_settings(tmp_path: Path) -> AppSettings:
    source_path = tmp_path / "sample_sources" / "dnd5e_hp_reference.md"
    source_path.parent.mkdir()
    source_path.write_text(
        "# HP Reference\n\n"
        "Section: Paladin\n"
        "Paladin level 1 HP is 10 plus Constitution modifier.\n"
        "After level 1 use fixed 6 plus Constitution modifier or rolled d10 plus modifier.\n",
        encoding="utf-8",
    )
    settings_path = tmp_path / "settings" / "approved_sources.json"
    settings_path.parent.mkdir()
    settings_path.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "path": "sample_sources/dnd5e_hp_reference.md",
                        "label": "HP Reference",
                        "description": "Demo HP source",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return AppSettings(
        repo_root=tmp_path,
        approved_sources_path=settings_path,
        runs_root=tmp_path / "python-agent-runs",
        chat_base_url="http://local.test/v1",
        chat_api_key="test-key",
        chat_model="test-model",
        chat_temperature=0.0,
        chat_timeout_seconds=120.0,
        worker_image="cli-agent-worker:test",
        worker_timeout_seconds=30,
        worker_queue_timeout_seconds=30.0,
        max_concurrent_worker_runs=2,
        max_sources_per_run=4,
        max_source_bytes=32 * 1024 * 1024,
        max_total_source_bytes_per_run=64 * 1024 * 1024,
        copilot_provider_base_url="http://host.docker.internal:8000/v1",
        copilot_model="test-copilot-model",
        copilot_provider_api_key=None,
        copilot_offline=True,
        docker_network=None,
    )


def with_settings_path(settings: AppSettings, path: Path) -> AppSettings:
    return replace(settings, approved_sources_path=path)
