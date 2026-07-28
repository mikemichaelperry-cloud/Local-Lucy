"""Level 1 deterministic tests for the state-manager split.

These tests exercise the low-level schema, queries, and manager layers using
temporary SQLite databases. They do not import Ollama or touch the network.
"""
from __future__ import annotations

import sqlite3

import pytest

pytestmark = [pytest.mark.deterministic]


@pytest.fixture
def fresh_conn(tmp_path):
    """Return a fresh SQLite connection with the state schema applied."""
    db_path = tmp_path / "state.db"
    # Use autocommit mode so tests can explicitly control BEGIN/COMMIT/ROLLBACK.
    conn = sqlite3.connect(str(db_path), timeout=30.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    # Import and apply migrations directly to test the schema layer.
    from router_py.schema_migrations import apply_migrations

    apply_migrations(conn)
    yield conn
    conn.close()


@pytest.fixture
def queries():
    """Import the queries module once per session."""
    from router_py.state import queries

    return queries


def test_schema_initialization_is_idempotent(fresh_conn):
    """Re-applying migrations on an up-to-date DB must be a no-op."""
    from router_py.schema_migrations import (
        LATEST_SCHEMA_VERSION,
        apply_migrations,
    )

    version1 = apply_migrations(fresh_conn)
    version2 = apply_migrations(fresh_conn)
    assert version1 == LATEST_SCHEMA_VERSION
    assert version2 == LATEST_SCHEMA_VERSION


def test_migration_forward_guard_raises_on_future_version(fresh_conn):
    """A DB newer than the application supports must raise RuntimeError."""
    from router_py.schema_migrations import LATEST_SCHEMA_VERSION, apply_migrations

    fresh_conn.execute(f"PRAGMA user_version = {LATEST_SCHEMA_VERSION + 10}")
    fresh_conn.commit()
    with pytest.raises(RuntimeError):
        apply_migrations(fresh_conn)


def test_foreign_keys_are_enforced(fresh_conn):
    """Foreign-key constraints must reject inserts for missing namespaces."""
    fresh_conn.execute("PRAGMA foreign_keys=ON")
    with pytest.raises(sqlite3.IntegrityError):
        fresh_conn.execute(
            "INSERT INTO routes (namespace_id, intent, confidence) VALUES (?, ?, ?)",
            (9999, "search", 0.9),
        )


def test_queries_do_not_independently_commit_batch(fresh_conn, queries):
    """write_batch must not commit a transaction it does not own.

    The queries layer is responsible for executing SQL, not for deciding
    transaction boundaries. When called inside a rollback, its work must
    also roll back.
    """
    ns_id = queries.ensure_namespace(fresh_conn, "test_ns")
    fresh_conn.execute("BEGIN")
    try:
        queries.write_batch(
            fresh_conn,
            ns_id,
            {"intent": "rollback_test", "confidence": 0.8},
            {"success": True},
        )
        fresh_conn.rollback()
    except Exception:
        fresh_conn.rollback()
        raise

    assert queries.read_last_route(fresh_conn, ns_id) is None
    assert queries.read_last_outcome(fresh_conn, ns_id) is None


def test_write_batch_persists_when_explicitly_committed(fresh_conn, queries):
    """write_batch must persist when the caller commits the transaction."""
    ns_id = queries.ensure_namespace(fresh_conn, "test_ns")
    fresh_conn.execute("BEGIN")
    queries.write_batch(
        fresh_conn,
        ns_id,
        {"intent": "commit_test", "confidence": 0.8},
        {"success": True},
    )
    fresh_conn.commit()

    route = queries.read_last_route(fresh_conn, ns_id)
    outcome = queries.read_last_outcome(fresh_conn, ns_id)
    assert route is not None
    assert route["intent"] == "commit_test"
    assert outcome is not None
    assert outcome["success"] is True


def test_namespace_isolation(fresh_conn, queries):
    """Data written in one namespace must not be visible in another."""
    ns_a = queries.ensure_namespace(fresh_conn, "ns_a")
    ns_b = queries.ensure_namespace(fresh_conn, "ns_b")

    fresh_conn.execute("BEGIN")
    queries.write_route(fresh_conn, ns_a, {"intent": "a", "confidence": 0.9})
    fresh_conn.commit()

    assert queries.read_last_route(fresh_conn, ns_a) is not None
    assert queries.read_last_route(fresh_conn, ns_b) is None


def test_session_expiration_deletes_stale_row(fresh_conn, queries):
    """Expired sessions must be removed and return None."""
    ns_id = queries.ensure_namespace(fresh_conn, "session_ns")
    queries.write_session(fresh_conn, ns_id, "expired", {"x": 1}, ttl_seconds=-1)
    fresh_conn.commit()

    assert queries.read_session(fresh_conn, ns_id, "expired") is None

    # Verify the row was actually deleted, not just returned as None.
    cursor = fresh_conn.execute(
        "SELECT COUNT(*) FROM sessions WHERE session_key = ?", ("expired",)
    )
    assert cursor.fetchone()[0] == 0


def test_lock_ownership_is_enforced(fresh_conn, queries):
    """Only the owner of a lock may release it."""
    ns_id = queries.ensure_namespace(fresh_conn, "lock_ns")
    assert queries.acquire_lock(fresh_conn, ns_id, "resource", "owner_a") is True
    fresh_conn.commit()

    # Different owner cannot release.
    assert queries.release_lock(fresh_conn, ns_id, "resource", "owner_b") is False
    fresh_conn.commit()
    assert queries.is_locked(fresh_conn, ns_id, "resource") is True

    # Original owner can release.
    assert queries.release_lock(fresh_conn, ns_id, "resource", "owner_a") is True
    fresh_conn.commit()
    assert queries.is_locked(fresh_conn, ns_id, "resource") is False


def test_state_manager_uses_split_schema_and_queries(tmp_path):
    """StateManager must initialize through the split schema/queries modules."""
    import os

    db_path = tmp_path / "state" / "lucy_state.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    old = os.environ.get("LUCY_STATE_DB")
    os.environ["LUCY_STATE_DB"] = str(db_path)
    try:
        from router_py.state_manager import StateManager

        sm = StateManager(namespace="split_test")
        sm.write_route({"intent": "local", "confidence": 0.95})
        route = sm.read_last_route()
        assert route is not None
        assert route["intent"] == "local"
        sm.close()
    finally:
        if old is None:
            os.environ.pop("LUCY_STATE_DB", None)
        else:
            os.environ["LUCY_STATE_DB"] = old
