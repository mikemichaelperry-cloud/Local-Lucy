#!/usr/bin/env python3
"""SQLite schema and migration helpers for Local Lucy state."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Optional

try:
    from ..schema_migrations import apply_migrations
except ImportError:
    from schema_migrations import apply_migrations


logger = logging.getLogger(__name__)

SCHEMA_SQL = """
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


def init_database(db_path: Optional[Path] = None) -> bool:
    """Initialize database without creating a StateManager instance.

    Useful for setup scripts and migrations.

    Args:
        db_path: Path to database file (default: state/lucy_state.db)

    Returns:
        bool: True if initialization succeeded
    """
    try:
        if db_path is None:
            router_root = Path(__file__).parent.parent.parent
            db_path = router_root / "state" / "lucy_state.db"

        db_path.parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(str(db_path), timeout=30.0)
        try:
            version = apply_migrations(conn)
            logger.info(f"Database initialized at {db_path} (version {version})")
            return True
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        return False
