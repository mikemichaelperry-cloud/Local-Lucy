"""Tests for tools.migrate_from_v10.

These tests exercise the migration utility with synthetic V10 state in
temporary directories so the real V10 and V11 installations are never touched.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from tools import migrate_from_v10


def _make_memory_db(path: Path, facts: list[tuple[str, str | None]] | None = None) -> None:
    """Create a minimal V10-compatible memory database."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS persistent_facts (
                id INTEGER PRIMARY KEY,
                fact_text TEXT,
                category TEXT,
                embedding BLOB,
                embedding_model TEXT,
                created_at TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS conversation_turns (
                id INTEGER PRIMARY KEY,
                session_id TEXT,
                role TEXT,
                text TEXT,
                created_at TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS session_metadata (
                session_id TEXT PRIMARY KEY,
                display_name TEXT,
                first_query TEXT,
                created_at TIMESTAMP
            )
            """
        )
        for fact_text, category in facts or []:
            conn.execute(
                "INSERT INTO persistent_facts (fact_text, category, created_at) VALUES (?, ?, datetime('now'))",
                (fact_text, category),
            )
        conn.commit()
    finally:
        conn.close()


def _make_state_db(path: Path) -> None:
    """Create a minimal V10-compatible lucy_state database."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                created_at TIMESTAMP
            )
            """
        )
        conn.execute("INSERT INTO sessions (session_id, created_at) VALUES (?, datetime('now'))", ("test-session",))
        conn.commit()
    finally:
        conn.close()


def _jsonl_lines(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


@pytest.fixture
def isolated_v10_v11(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Create isolated V10 root/runtime and a V11 namespace root."""
    v10_root = tmp_path / "lucy-v10"
    v10_runtime = tmp_path / "runtime-v10"
    v11_root = tmp_path / "local-lucy-v11"

    # V11 namespace override so xdg_paths writes into the temp directory.
    monkeypatch.setenv("LUCY_RUNTIME_NAMESPACE_ROOT", str(v11_root))
    # Point defaults at our temp V10 directories.
    monkeypatch.setattr(migrate_from_v10, "DEFAULT_V10_ROOTS", [v10_root])
    monkeypatch.setattr(migrate_from_v10, "DEFAULT_V10_RUNTIME_ROOT", v10_runtime)

    return {
        "v10_root": v10_root,
        "v10_runtime": v10_runtime,
        "v11_root": v11_root,
        "v11_state": v11_root / "state",
    }


def test_dry_run_discovers_all_sources(isolated_v10_v11: dict[str, Path]) -> None:
    v10_root = isolated_v10_v11["v10_root"]
    v10_runtime = isolated_v10_v11["v10_runtime"]
    v11_state = isolated_v10_v11["v11_state"]

    _make_state_db(v10_root / "state" / "lucy_state.db")
    _make_memory_db(v10_runtime / "state" / "memory.db", facts=[("Mike is 66", "identity")])
    (v10_runtime / "state" / "current_state.json").write_text(json.dumps({"mode": "offline"}))
    (v10_runtime / "state" / "request_history.jsonl").write_text('{"request_id":"r1"}\n')
    (v10_runtime / "state" / "request_history.20260607-174407.jsonl").write_text('{"request_id":"r2"}\n{"request_id":"r3"}\n')

    ret = migrate_from_v10.main(["dry-run"])
    assert ret == 0


def test_migrate_copies_databases_and_json_and_history_archives(
    isolated_v10_v11: dict[str, Path],
) -> None:
    v10_root = isolated_v10_v11["v10_root"]
    v10_runtime = isolated_v10_v11["v10_runtime"]
    v11_state = isolated_v10_v11["v11_state"]

    _make_state_db(v10_root / "state" / "lucy_state.db")
    _make_memory_db(
        v10_runtime / "state" / "memory.db",
        facts=[("Mike is 66", "identity"), ("Oscar is a dog", "family")],
    )
    (v10_runtime / "state" / "current_state.json").write_text(json.dumps({"mode": "offline"}))
    (v10_runtime / "state" / "request_history.jsonl").write_text('{"request_id":"r1"}\n')
    (v10_runtime / "state" / "request_history.20260607-174407.jsonl").write_text('{"request_id":"r2"}\n{"request_id":"r3"}\n')

    ret = migrate_from_v10.main(["migrate", "--force"])
    assert ret == 0

    assert (v11_state / "lucy_state.db").is_file()
    assert (v11_state / "memory.db").is_file()
    assert (v11_state / "current_state.json").is_file()
    assert (v11_state / "request_history.jsonl").is_file()
    assert (v11_state / "request_history.20260607-174407.jsonl").is_file()

    # Verify row counts.
    conn = sqlite3.connect(v11_state / "memory.db")
    try:
        facts_count = conn.execute("SELECT COUNT(*) FROM persistent_facts").fetchone()[0]
        assert facts_count == 2
    finally:
        conn.close()

    assert _jsonl_lines(v11_state / "request_history.jsonl") == 1
    assert _jsonl_lines(v11_state / "request_history.20260607-174407.jsonl") == 2

    # Verify command should pass now.
    ret = migrate_from_v10.main(["verify"])
    assert ret == 0


def test_migrate_refuses_without_force_when_v11_state_exists(
    isolated_v10_v11: dict[str, Path],
) -> None:
    v10_root = isolated_v10_v11["v10_root"]
    v10_runtime = isolated_v10_v11["v10_runtime"]
    v11_state = isolated_v10_v11["v11_state"]

    _make_state_db(v10_root / "state" / "lucy_state.db")
    _make_memory_db(v10_runtime / "state" / "memory.db")
    # Pre-existing V11 memory database.
    v11_state.mkdir(parents=True, exist_ok=True)
    _make_memory_db(v11_state / "memory.db")

    ret = migrate_from_v10.main(["migrate"])
    assert ret == 1


def test_migrate_does_not_modify_v10_sources(
    isolated_v10_v11: dict[str, Path],
) -> None:
    v10_root = isolated_v10_v11["v10_root"]
    v10_runtime = isolated_v10_v11["v10_runtime"]

    _make_state_db(v10_root / "state" / "lucy_state.db")
    _make_memory_db(v10_runtime / "state" / "memory.db", facts=[("Fact one", None)])
    (v10_runtime / "state" / "current_state.json").write_text(json.dumps({"mode": "offline"}))

    v10_state_mtime_before = (v10_root / "state" / "lucy_state.db").stat().st_mtime
    v10_memory_mtime_before = (v10_runtime / "state" / "memory.db").stat().st_mtime

    ret = migrate_from_v10.main(["migrate", "--force"])
    assert ret == 0

    assert (v10_root / "state" / "lucy_state.db").stat().st_mtime == v10_state_mtime_before
    assert (v10_runtime / "state" / "memory.db").stat().st_mtime == v10_memory_mtime_before


def test_verify_fails_when_destination_is_missing(
    isolated_v10_v11: dict[str, Path],
) -> None:
    ret = migrate_from_v10.main(["verify"])
    assert ret == 1
