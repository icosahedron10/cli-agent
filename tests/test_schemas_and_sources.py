from __future__ import annotations

import json
from pathlib import Path

import pytest

from dci_poc.constants import API_TOOL_AUTO_ANALYSIS, API_TOOL_DCI_SEARCH
from dci_poc.exceptions import ApprovedSourceError
from dci_poc.schemas import build_tool_schemas
from dci_poc.services.approved_sources import ApprovedSourceService


def test_tool_schema_uses_api_safe_names_and_source_enum(app_config) -> None:
    sources = ApprovedSourceService(app_config)
    schemas = build_tool_schemas(sources.approved_paths())

    names = [schema["function"]["name"] for schema in schemas]
    assert names == [API_TOOL_DCI_SEARCH, API_TOOL_AUTO_ANALYSIS]

    for schema in schemas:
        source_items = schema["function"]["parameters"]["properties"]["source_paths"]["items"]
        assert source_items["enum"] == ["sample_sources/dnd5e_hp_reference.md"]
        assert schema["function"]["parameters"]["additionalProperties"] is False


def test_approved_source_validation_accepts_exact_shortlist(app_config) -> None:
    sources = ApprovedSourceService(app_config)

    entries = sources.validate_requested_paths(["sample_sources/dnd5e_hp_reference.md"])

    assert len(entries) == 1
    assert entries[0].absolute_path.exists()


def test_approved_source_validation_rejects_unknown_path(app_config) -> None:
    sources = ApprovedSourceService(app_config)

    with pytest.raises(ApprovedSourceError, match="Unapproved source path"):
        sources.validate_requested_paths(["sample_sources/other.md"])


def test_approved_sources_reject_path_escape(app_config, tmp_path: Path) -> None:
    config_path = tmp_path / "bad_sources.json"
    config_path.write_text(
        json.dumps({"sources": [{"path": "../outside.md", "label": "Bad", "description": ""}]}),
        encoding="utf-8",
    )
    config = app_config.__class__(**{**app_config.__dict__, "approved_sources_path": config_path})

    with pytest.raises(ApprovedSourceError, match="escapes repo root"):
        ApprovedSourceService(config)

