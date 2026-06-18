from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from cli_agent.constants import API_TOOL_AUTO_ANALYSIS, API_TOOL_SOURCE_SEARCH, MAX_ANALYSIS_GOAL_LENGTH
from cli_agent.exceptions import ApprovedSourceError
from cli_agent.schemas import build_tool_schemas
from cli_agent.services.approved_sources import ApprovedSourceService


def test_tool_schema_uses_api_safe_names_and_source_enum(app_settings) -> None:
    sources = ApprovedSourceService(app_settings)
    schemas = build_tool_schemas(
        sources.approved_paths(),
        max_sources_per_run=app_settings.max_sources_per_run,
    )

    names = [schema["function"]["name"] for schema in schemas]
    assert names == [API_TOOL_SOURCE_SEARCH, API_TOOL_AUTO_ANALYSIS]

    for schema in schemas:
        source_paths = schema["function"]["parameters"]["properties"]["source_paths"]
        source_items = source_paths["items"]
        assert source_items["enum"] == ["sample_sources/dnd5e_hp_reference.md"]
        assert source_paths["maxItems"] == app_settings.max_sources_per_run
        assert schema["function"]["parameters"]["additionalProperties"] is False

    auto_analysis = next(schema for schema in schemas if schema["function"]["name"] == API_TOOL_AUTO_ANALYSIS)
    analysis_goal = auto_analysis["function"]["parameters"]["properties"]["analysis_goal"]
    assert analysis_goal["maxLength"] == MAX_ANALYSIS_GOAL_LENGTH
    assert "single-line" in analysis_goal["description"]


def test_approved_source_validation_accepts_exact_shortlist(app_settings) -> None:
    sources = ApprovedSourceService(app_settings)

    entries = sources.validate_requested_paths(["sample_sources/dnd5e_hp_reference.md"])

    assert len(entries) == 1
    assert entries[0].absolute_path.exists()
    assert entries[0].size_bytes > 0


def test_approved_source_validation_rejects_unknown_path(app_settings) -> None:
    sources = ApprovedSourceService(app_settings)

    with pytest.raises(ApprovedSourceError, match="Unapproved source path"):
        sources.validate_requested_paths(["sample_sources/other.md"])


def test_approved_sources_reject_path_escape(app_settings, tmp_path: Path) -> None:
    settings_path = tmp_path / "bad_sources.json"
    settings_path.write_text(
        json.dumps({"sources": [{"path": "../outside.md", "label": "Bad", "description": ""}]}),
        encoding="utf-8",
    )
    settings = app_settings.__class__(**{**app_settings.__dict__, "approved_sources_path": settings_path})

    with pytest.raises(ApprovedSourceError, match="escapes repo root"):
        ApprovedSourceService(settings)


def test_approved_source_validation_rejects_too_many_sources(app_settings) -> None:
    source_paths = []
    for index in range(3):
        source_path = app_settings.repo_root / f"source_{index}.md"
        source_path.write_text(f"Source {index}", encoding="utf-8")
        source_paths.append(source_path.name)

    settings_path = app_settings.repo_root / "many_sources.json"
    settings_path.write_text(
        json.dumps(
            {
                "sources": [
                    {"path": path, "label": path, "description": ""}
                    for path in source_paths
                ]
            }
        ),
        encoding="utf-8",
    )
    settings = replace(app_settings, approved_sources_path=settings_path, max_sources_per_run=2)
    sources = ApprovedSourceService(settings)

    with pytest.raises(ApprovedSourceError, match="maximum per run is 2"):
        sources.validate_requested_paths(source_paths)


def test_approved_source_validation_rejects_oversized_source(app_settings) -> None:
    source_path = app_settings.repo_root / "large_source.md"
    source_path.write_text("abcdef", encoding="utf-8")
    settings_path = app_settings.repo_root / "large_source_settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "sources": [
                    {"path": source_path.name, "label": "Large", "description": ""}
                ]
            }
        ),
        encoding="utf-8",
    )
    settings = replace(app_settings, approved_sources_path=settings_path, max_source_bytes=5)
    sources = ApprovedSourceService(settings)

    with pytest.raises(ApprovedSourceError, match="too large"):
        sources.validate_requested_paths([source_path.name])


def test_approved_source_validation_rejects_total_source_bytes(app_settings) -> None:
    source_paths = []
    for index in range(2):
        source_path = app_settings.repo_root / f"total_source_{index}.md"
        source_path.write_text("abcd", encoding="utf-8")
        source_paths.append(source_path.name)

    settings_path = app_settings.repo_root / "total_sources_settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "sources": [
                    {"path": path, "label": path, "description": ""}
                    for path in source_paths
                ]
            }
        ),
        encoding="utf-8",
    )
    settings = replace(
        app_settings,
        approved_sources_path=settings_path,
        max_source_bytes=10,
        max_total_source_bytes_per_run=7,
    )
    sources = ApprovedSourceService(settings)

    with pytest.raises(ApprovedSourceError, match="Requested sources total"):
        sources.validate_requested_paths(source_paths)
