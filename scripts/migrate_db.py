#!/usr/bin/env python3
"""Local Lucy v10 — Database Schema Migration

Handles schema versioning and migrations for SQLite databases.

Usage:
    python scripts/migrate_db.py              # migrate state DB
    python scripts/migrate_db.py --memory     # migrate memory DB
    python scripts/migrate_db.py --dry-run    # show what would change
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Schema versions
# ---------------------------------------------------------------------------

_CURRENT_STATE_VERSION = 1
_CURRENT_MEMORY_VERSION = 1

_STATE_MIGRATIONS: dict[int, list[str]] = {
    0: [
        """
        CREATE TABLE IF NOT EXISTS namespaces (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS routes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            namespace_id INTEGER NOT NULL,
            intent TEXT NOT NULL,
            confidence REAL NOT NULL,
            strategy TEXT,
            metadata TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (namespace_id) REFERENCES namespaces(id) ON DELETE CASCADE
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS outcomes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            namespace_id INTEGER NOT NULL,
            route_id INTEGER,
            success BOOLEAN NOT NULL,
            duration_ms INTEGER,
            result TEXT,
            error_message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (namespace_id) REFERENCES namespaces(id) ON DELETE CASCADE
        );
        """,
    ],
}

_MEMORY_MIGRATIONS: dict[int, list[str]] = {
    0: [
        """
        CREATE TABLE IF NOT EXISTS conversation_turns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL DEFAULT 'default',
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp REAL DEFAULT (unixepoch())
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS persistent_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT,
            key TEXT,
            value TEXT,
            source TEXT,
            confidence REAL DEFAULT 1.0,
            embedding BLOB,
            created_at REAL DEFAULT (unixepoch()),
            updated_at REAL DEFAULT (unixepoch())
        );
        """,
    ],
}


def _get_user_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("PRAGMA user_version").fetchone()
    return row[0] if row else 0


def _set_user_version(conn: sqlite3.Connection, version: int) -> None:
    conn.execute(f"PRAGMA user_version = {version}")


def migrate(
    db_path: Path,
    migrations: dict[int, list[str]],
    target_version: int,
    *,
    dry_run: bool = False,
) -> bool:
    """Apply pending migrations. Returns True if changes were made."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    try:
        current = _get_user_version(conn)
        if current >= target_version:
            print(f"  [{db_path}] already at version {current}")
            return False

        print(f"  [{db_path}] migrating {current} → {target_version}")
        for version in range(current, target_version):
            stmts = migrations.get(version, [])
            for stmt in stmts:
                stmt = stmt.strip()
                if not stmt:
                    continue
                if dry_run:
                    print(f"    would execute: {stmt[:60]}...")
                else:
                    conn.executescript(stmt)
            if not dry_run:
                _set_user_version(conn, version + 1)
                conn.commit()
        if not dry_run:
            print(f"  [{db_path}] migrated to version {target_version}")
        return True
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Local Lucy DB migration")
    parser.add_argument("--memory", action="store_true", help="migrate memory DB")
    parser.add_argument("--state", action="store_true", help="migrate state DB")
    parser.add_argument("--dry-run", action="store_true", help="show only, do not apply")
    args = parser.parse_args()

    changed = False

    # If neither specified, do both
    if not args.memory and not args.state:
        args.memory = True
        args.state = True

    if args.state:
        print("[state DB]")
        state_db = Path(os.environ.get("LUCY_STATE_DB", "state/lucy_state.db")).expanduser()
        if migrate(state_db, _STATE_MIGRATIONS, _CURRENT_STATE_VERSION, dry_run=args.dry_run):
            changed = True

    if args.memory:
        print("[memory DB]")
        memory_db = Path(os.environ.get("LUCY_MEMORY_DB_PATH", "~/.codex-api-home/lucy/runtime-v10/state/memory.db")).expanduser()
        if migrate(memory_db, _MEMORY_MIGRATIONS, _CURRENT_MEMORY_VERSION, dry_run=args.dry_run):
            changed = True

    if args.dry_run:
        print("\nDry run complete. No changes applied.")
    elif changed:
        print("\nMigration complete.")
    else:
        print("\nNothing to migrate.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
