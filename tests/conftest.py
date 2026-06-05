from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import json

import pytest

from dci_poc.models import AppConfig


@pytest.fixture
def app_config(tmp_path: Path) -> AppConfig:
    source_path = tmp_path / "sample_sources" / "dnd5e_hp_reference.md"
    source_path.parent.mkdir()
    source_path.write_text(
        "# HP Reference\n\n"
        "Section: Paladin\n"
        "Paladin level 1 HP is 10 plus Constitution modifier.\n"
        "After level 1 use fixed 6 plus Constitution modifier or rolled d10 plus modifier.\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "config" / "approved_sources.json"
    config_path.parent.mkdir()
    config_path.write_text(
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
    return AppConfig(
        repo_root=tmp_path,
        approved_sources_path=config_path,
        runs_root=tmp_path / "python-agent-runs",
        chat_base_url="http://local.test/v1",
        chat_api_key="test-key",
        chat_model="test-model",
        chat_temperature=0.0,
        worker_image="dci-copilot-worker:test",
        worker_timeout_seconds=30,
        copilot_provider_base_url="http://host.docker.internal:11434",
        copilot_model="test-copilot-model",
        copilot_provider_api_key=None,
        copilot_offline=True,
        docker_network=None,
    )


def with_config_path(config: AppConfig, path: Path) -> AppConfig:
    return replace(config, approved_sources_path=path)


