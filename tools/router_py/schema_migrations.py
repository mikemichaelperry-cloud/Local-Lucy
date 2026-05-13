#!/usr/bin/env python3
"""
Versioned SQLite schema migrations for Local Lucy V8.

Uses PRAGMA user_version for tracking.  Migrations are applied
automatically when StateManager initializes the database.

Properties:
- Idempotent: re-running on an up-to-date DB is a no-op.
- Non-destructive: never drops user data.
- Rollback-safe: each migration runs inside its own transaction.
- Forward-guard: databases newer than LATEST_SCHEMA_VERSION raise RuntimeError.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

LATEST_SCHEMA_VERSION = 2

Migration = Callable[[sqlite3.Connection], None]

# ---------------------------------------------------------------------------
# v1 — initial schema
# ---------------------------------------------------------------------------
MIGRATION_V1_SQL = """
-- Enable WAL mode for concurrent access
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- Namespaces for isolation
CREATE TABLE IF NOT EXISTS namespaces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Routes table: stores routing decisions
CREATE TABLE IF NOT EXISTS routes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    namespace_id INTEGER NOT NULL,
    intent TEXT NOT NULL,
    confidence REAL NOT NULL,
    strategy TEXT,
    metadata TEXT,  -- JSON blob
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (namespace_id) REFERENCES namespaces(id) ON DELETE CASCADE
);

-- Outcomes table: stores execution results
CREATE TABLE IF NOT EXISTS outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    namespace_id INTEGER NOT NULL,
    route_id INTEGER,
    success BOOLEAN NOT NULL,
    duration_ms INTEGER,
    result TEXT,  -- JSON blob
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (namespace_id) REFERENCES namespaces(id) ON DELETE CASCADE,
    FOREIGN KEY (route_id) REFERENCES routes(id) ON DELETE SET NULL
);

-- Sessions table: tracks active sessions
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    namespace_id INTEGER NOT NULL,
    session_key TEXT NOT NULL,
    data TEXT,  -- JSON blob
    expires_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(namespace_id, session_key),
    FOREIGN KEY (namespace_id) REFERENCES namespaces(id) ON DELETE CASCADE
);

-- Telemetry table: metrics and events
CREATE TABLE IF NOT EXISTS telemetry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    namespace_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    event_data TEXT,  -- JSON blob
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (namespace_id) REFERENCES namespaces(id) ON DELETE CASCADE
);

-- Distributed locks table
CREATE TABLE IF NOT EXISTS locks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    namespace_id INTEGER NOT NULL,
    lock_name TEXT NOT NULL,
    owner TEXT NOT NULL,
    acquired_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NOT NULL,
    UNIQUE(namespace_id, lock_name),
    FOREIGN KEY (namespace_id) REFERENCES namespaces(id) ON DELETE CASCADE
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_routes_namespace_created 
    ON routes(namespace_id, created_at);
CREATE INDEX IF NOT EXISTS idx_outcomes_namespace_created 
    ON outcomes(namespace_id, created_at);
CREATE INDEX IF NOT EXISTS idx_sessions_key 
    ON sessions(session_key);
CREATE INDEX IF NOT EXISTS idx_telemetry_namespace_type 
    ON telemetry(namespace_id, event_type, created_at);
CREATE INDEX IF NOT EXISTS idx_locks_expires 
    ON locks(expires_at);
"""


def _get_user_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("PRAGMA user_version").fetchone()
    return int(row[0]) if row else 0


def _set_user_version(conn: sqlite3.Connection, version: int) -> None:
    # PRAGMA user_version cannot be parameterized, but the value is an int
    conn.execute(f"PRAGMA user_version = {int(version)}")


def _migration_v1(conn: sqlite3.Connection) -> None:
    """Create initial schema: tables, indexes, WAL mode."""
    conn.executescript(MIGRATION_V1_SQL)


def _migration_v2(conn: sqlite3.Connection) -> None:
    """Fix old sessions table from session_key UNIQUE to composite UNIQUE."""
    cursor = conn.execute("PRAGMA index_list(sessions)")
    indexes = {row[1]: row for row in cursor.fetchall()}
    if "sqlite_autoindex_sessions_1" not in indexes:
        return  # Already correct or table doesn't exist yet

    cursor = conn.execute("PRAGMA index_info(sqlite_autoindex_sessions_1)")
    cols = [row[2] for row in cursor.fetchall()]
    if cols != ["session_key"]:
        return  # Already composite or different structure

    conn.execute("ALTER TABLE sessions RENAME TO sessions_old")
    conn.executescript("""
        CREATE TABLE sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            namespace_id INTEGER NOT NULL,
            session_key TEXT NOT NULL,
            data TEXT,
            expires_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(namespace_id, session_key),
            FOREIGN KEY (namespace_id) REFERENCES namespaces(id) ON DELETE CASCADE
        );
        INSERT INTO sessions (
            id, namespace_id, session_key, data, expires_at, created_at, updated_at
        )
        SELECT id, namespace_id, session_key, data, expires_at, created_at, updated_at
        FROM sessions_old;
        DROP TABLE sessions_old;
    """)


MIGRATIONS: dict[int, Migration] = {
    1: _migration_v1,
    2: _migration_v2,
}


def apply_migrations(conn: sqlite3.Connection) -> int:
    """
    Apply pending migrations to the given SQLite connection.

    Args:
        conn: An open sqlite3.Connection.

    Returns:
        The schema version after migrations complete.

    Raises:
        RuntimeError: If the DB version is newer than LATEST_SCHEMA_VERSION.
        Exception: If a migration fails; the transaction is rolled back.
    """
    current = _get_user_version(conn)

    if current > LATEST_SCHEMA_VERSION:
        raise RuntimeError(
            f"Database schema version {current} is newer than supported "
            f"{LATEST_SCHEMA_VERSION}.  Downgrade or update the application."
        )

    if current == LATEST_SCHEMA_VERSION:
        return current

    for target_version in range(current + 1, LATEST_SCHEMA_VERSION + 1):
        migration = MIGRATIONS[target_version]
        try:
            conn.execute("BEGIN")
            migration(conn)
            _set_user_version(conn, target_version)
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    return _get_user_version(conn)
