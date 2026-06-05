from __future__ import annotations

import os
from pathlib import Path

from dci_poc.constants import RUNS_DIR_NAME
from dci_poc.exceptions import ConfigurationError
from dci_poc.models import AppConfig


def load_app_config(repo_root: Path | None = None) -> AppConfig:
    root = (repo_root or Path.cwd()).resolve()
    approved_sources_path = Path(
        os.getenv("DCI_APPROVED_SOURCES_PATH", root / "config" / "approved_sources.json")
    )
    if not approved_sources_path.is_absolute():
        approved_sources_path = root / approved_sources_path

    runs_root = Path(os.getenv("DCI_RUNS_ROOT", root / RUNS_DIR_NAME))
    if not runs_root.is_absolute():
        runs_root = root / runs_root

    worker_timeout_seconds = _read_int_env("DCI_WORKER_TIMEOUT_SECONDS", 180)
    worker_queue_timeout_seconds = _read_non_negative_float_env("DCI_WORKER_QUEUE_TIMEOUT_SECONDS", 30.0)
    max_concurrent_worker_runs = _read_int_env("DCI_MAX_CONCURRENT_WORKER_RUNS", 2)
    max_sources_per_run = _read_int_env("DCI_MAX_SOURCES_PER_RUN", 4)
    max_source_bytes = _read_int_env("DCI_MAX_SOURCE_BYTES", 32 * 1024 * 1024)
    max_total_source_bytes_per_run = _read_int_env("DCI_MAX_TOTAL_SOURCE_BYTES_PER_RUN", 64 * 1024 * 1024)
    chat_temperature = _read_float_env("DCI_CHAT_TEMPERATURE", 0.0)
    chat_timeout_seconds = _read_positive_float_env("DCI_CHAT_TIMEOUT_SECONDS", 120.0)

    chat_base_url = os.getenv("DCI_CHAT_BASE_URL", "http://localhost:11434/v1").rstrip("/")
    chat_model = os.getenv("DCI_CHAT_MODEL", "llama3.2")
    copilot_base_url = os.getenv("COPILOT_PROVIDER_BASE_URL", "http://host.docker.internal:11434")
    copilot_model = os.getenv("COPILOT_MODEL", chat_model)

    return AppConfig(
        repo_root=root,
        approved_sources_path=approved_sources_path.resolve(),
        runs_root=runs_root.resolve(),
        chat_base_url=chat_base_url,
        chat_api_key=os.getenv("DCI_CHAT_API_KEY", "not-needed"),
        chat_model=chat_model,
        chat_temperature=chat_temperature,
        chat_timeout_seconds=chat_timeout_seconds,
        worker_image=os.getenv("DCI_WORKER_IMAGE", "dci-copilot-worker:local"),
        worker_timeout_seconds=worker_timeout_seconds,
        worker_queue_timeout_seconds=worker_queue_timeout_seconds,
        max_concurrent_worker_runs=max_concurrent_worker_runs,
        max_sources_per_run=max_sources_per_run,
        max_source_bytes=max_source_bytes,
        max_total_source_bytes_per_run=max_total_source_bytes_per_run,
        copilot_provider_base_url=copilot_base_url,
        copilot_model=copilot_model,
        copilot_provider_api_key=os.getenv("COPILOT_PROVIDER_API_KEY"),
        copilot_offline=_read_bool_env("COPILOT_OFFLINE", True),
        docker_network=os.getenv("DCI_DOCKER_NETWORK") or None,
    )


def _read_int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc
    if parsed <= 0:
        raise ConfigurationError(f"{name} must be greater than zero")
    return parsed


def _read_float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be a number") from exc


def _read_positive_float_env(name: str, default: float) -> float:
    parsed = _read_float_env(name, default)
    if parsed <= 0:
        raise ConfigurationError(f"{name} must be greater than zero")
    return parsed


def _read_non_negative_float_env(name: str, default: float) -> float:
    parsed = _read_float_env(name, default)
    if parsed < 0:
        raise ConfigurationError(f"{name} must be zero or greater")
    return parsed


def _read_bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
