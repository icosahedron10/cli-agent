from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cli_agent.exceptions import ApprovedSourceError
from cli_agent.models import AppSettings, SourceEntry


class ApprovedSourceService:
    def __init__(self, settings: AppSettings) -> None:
        self._settings = settings
        self._sources_by_path = _load_sources(settings)

    def approved_paths(self) -> list[str]:
        return list(self._sources_by_path.keys())

    def all_sources(self) -> list[SourceEntry]:
        return list(self._sources_by_path.values())

    def validate_requested_paths(self, requested_paths: Any) -> list[SourceEntry]:
        if not isinstance(requested_paths, list) or not requested_paths:
            raise ApprovedSourceError("source_paths must be a non-empty list")

        entries: list[SourceEntry] = []
        seen: set[str] = set()
        for path in requested_paths:
            if not isinstance(path, str):
                raise ApprovedSourceError("source_paths entries must be strings")
            if path in seen:
                continue
            entry = self._sources_by_path.get(path)
            if entry is None:
                raise ApprovedSourceError(f"Unapproved source path requested: {path}")
            entries.append(entry)
            seen.add(path)

        _validate_source_limits(entries, self._settings)
        return entries


def _load_sources(settings: AppSettings) -> dict[str, SourceEntry]:
    if not settings.approved_sources_path.exists():
        raise ApprovedSourceError(f"Approved sources file does not exist: {settings.approved_sources_path}")

    try:
        raw = json.loads(settings.approved_sources_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ApprovedSourceError("Approved sources file must be valid JSON") from exc

    sources = raw.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ApprovedSourceError("Approved sources file must contain a non-empty sources list")

    loaded: dict[str, SourceEntry] = {}
    for index, item in enumerate(sources):
        entry = _parse_source_entry(settings.repo_root, item, index)
        if entry.path in loaded:
            raise ApprovedSourceError(f"Duplicate approved source path: {entry.path}")
        loaded[entry.path] = entry
    return loaded


def _parse_source_entry(repo_root: Path, item: Any, index: int) -> SourceEntry:
    if not isinstance(item, dict):
        raise ApprovedSourceError(f"Approved source #{index + 1} must be an object")

    path = item.get("path")
    label = item.get("label")
    description = item.get("description", "")
    if not isinstance(path, str) or not path.strip():
        raise ApprovedSourceError(f"Approved source #{index + 1} needs a non-empty path")
    if not isinstance(label, str) or not label.strip():
        raise ApprovedSourceError(f"Approved source {path} needs a non-empty label")
    if not isinstance(description, str):
        raise ApprovedSourceError(f"Approved source {path} description must be a string")

    if Path(path).is_absolute():
        raise ApprovedSourceError(f"Approved source path must be repo-relative: {path}")

    absolute_path = (repo_root / path).resolve()
    try:
        absolute_path.relative_to(repo_root.resolve())
    except ValueError as exc:
        raise ApprovedSourceError(f"Approved source path escapes repo root: {path}") from exc
    if not absolute_path.is_file():
        raise ApprovedSourceError(f"Approved source file does not exist: {path}")

    return SourceEntry(
        path=path,
        label=label,
        description=description,
        absolute_path=absolute_path,
        size_bytes=absolute_path.stat().st_size,
    )


def _validate_source_limits(entries: list[SourceEntry], settings: AppSettings) -> None:
    if len(entries) > settings.max_sources_per_run:
        raise ApprovedSourceError(
            f"Requested {len(entries)} sources; maximum per run is {settings.max_sources_per_run}."
        )

    oversized = [entry for entry in entries if entry.size_bytes > settings.max_source_bytes]
    if oversized:
        entry = oversized[0]
        raise ApprovedSourceError(
            f"Requested source is too large: {entry.path} is {_format_bytes(entry.size_bytes)}; "
            f"limit is {_format_bytes(settings.max_source_bytes)}."
        )

    total_size = sum(entry.size_bytes for entry in entries)
    if total_size > settings.max_total_source_bytes_per_run:
        raise ApprovedSourceError(
            f"Requested sources total {_format_bytes(total_size)}; "
            f"limit is {_format_bytes(settings.max_total_source_bytes_per_run)}."
        )


def _format_bytes(size_bytes: int) -> str:
    mib = size_bytes / (1024 * 1024)
    if mib >= 1:
        return f"{mib:.1f} MiB"
    kib = size_bytes / 1024
    if kib >= 1:
        return f"{kib:.1f} KiB"
    return f"{size_bytes} bytes"
