#!/usr/bin/env python3
"""Local Lucy v11 — XDG Base Directory compliance

Provides portable paths for data, config, cache, and runtime state.
Honours explicit ``LUCY_RUNTIME_NAMESPACE_ROOT`` overrides (used by tests).

Usage:
    from tools.xdg_paths import (
        lucy_data_dir,
        lucy_config_dir,
        lucy_cache_dir,
        lucy_runtime_namespace_root,
    )
"""

from __future__ import annotations

import os
from pathlib import Path

_APP_NAME = "local-lucy-v11"


def _xdg_dir(env_var: str, fallback: Path) -> Path:
    raw = os.environ.get(env_var, "").strip()
    if raw:
        return Path(raw).expanduser()
    return fallback.expanduser()


def lucy_data_dir() -> Path:
    """User data: persistent memory, embeddings, models."""
    legacy = os.environ.get("LUCY_RUNTIME_NAMESPACE_ROOT", "").strip()
    if legacy:
        return Path(legacy)
    fallback = Path.home() / ".local" / "share"
    return _xdg_dir("XDG_DATA_HOME", fallback) / _APP_NAME


def lucy_runtime_namespace_root() -> Path:
    """Runtime namespace root: alias for the canonical Lucy data directory.

    ``LUCY_RUNTIME_NAMESPACE_ROOT`` overrides this when explicitly set.
    """
    return lucy_data_dir()


def lucy_config_dir() -> Path:
    """User config: Modelfiles, prompts, trust rules."""
    fallback = Path.home() / ".config"
    return _xdg_dir("XDG_CONFIG_HOME", fallback) / _APP_NAME


def lucy_cache_dir() -> Path:
    """User cache: downloaded assets, temp build artifacts."""
    fallback = Path.home() / ".cache"
    return _xdg_dir("XDG_CACHE_HOME", fallback) / _APP_NAME


def lucy_state_dir() -> Path:
    """Runtime state: SQLite DBs, JSON state dumps, logs."""
    return lucy_data_dir() / "state"


def lucy_memory_db_path() -> Path:
    """Resolved memory database path."""
    raw = os.environ.get("LUCY_MEMORY_DB_PATH", "").strip()
    if raw:
        return Path(raw).expanduser()
    return lucy_state_dir() / "memory.db"


def lucy_state_db_path() -> Path:
    """Resolved state database path."""
    raw = os.environ.get("LUCY_STATE_DB", "").strip()
    if raw:
        return Path(raw).expanduser()
    return lucy_state_dir() / "lucy_state.db"
