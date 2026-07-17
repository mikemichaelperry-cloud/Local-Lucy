#!/usr/bin/env python3
"""
Tests for schema_migrations.py.

All tests use tmp_path — never touch the production runtime DB.
"""

import sqlite3
import pytest

try:
    from . import schema_migrations
except ImportError:
    import schema_migrations

apply_migrations = schema_migrations.apply_migrations
LATEST_SCHEMA_VERSION = schema_migrations.LATEST_SCHEMA_VERSION
MIGRATIONS = schema_migrations.MIGRATIONS


class TestSchemaMigrations:
    """Versioned SQLite migration safety and correctness."""

    # ------------------------------------------------------------------
    # 1. Fresh DB gets latest schema
    # ------------------------------------------------------------------
    def test_fresh_db_gets_latest_schema(self, tmp_path):
        db_path = tmp_path / "fresh.db"
        conn = sqlite3.connect(str(db_path))
        try:
            version = apply_migrations(conn)
            assert version == LATEST_SCHEMA_VERSION

            # Core tables must exist
            tables = {
                row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            assert "namespaces" in tables
            assert "routes" in tables
            assert "outcomes" in tables
            assert "sessions" in tables
            assert "telemetry" in tables
            assert "locks" in tables
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # 2. Existing empty DB upgrades from v0
    # ------------------------------------------------------------------
    def test_existing_empty_db_upgrades(self, tmp_path):
        db_path = tmp_path / "empty.db"
        conn = sqlite3.connect(str(db_path))
        try:
            # Simulate an untouched DB (user_version defaults to 0)
            conn.execute("PRAGMA user_version")
            version = apply_migrations(conn)
            assert version == LATEST_SCHEMA_VERSION

            tables = {
                row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            assert "namespaces" in tables
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # 3. Idempotent — second run is a no-op
    # ------------------------------------------------------------------
    def test_idempotent_second_run(self, tmp_path):
        db_path = tmp_path / "idempotent.db"
        conn = sqlite3.connect(str(db_path))
        try:
            v1 = apply_migrations(conn)
            v2 = apply_migrations(conn)
            assert v1 == v2 == LATEST_SCHEMA_VERSION
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # 4. Existing data is preserved across migration
    # ------------------------------------------------------------------
    def test_existing_data_preserved(self, tmp_path):
        db_path = tmp_path / "legacy.db"
        conn = sqlite3.connect(str(db_path))
        try:
            # Simulate a DB created by the old SCHEMA_SQL (v1)
            schema_migrations._migration_v1(conn)
            conn.execute("PRAGMA user_version = 1")
            conn.commit()

            # Insert a sample row
            conn.execute("INSERT INTO namespaces (name) VALUES (?)", ("test_ns",))
            conn.commit()

            # Now run migrations (should apply v2)
            version = apply_migrations(conn)
            assert version == LATEST_SCHEMA_VERSION

            # Data must survive
            row = conn.execute(
                "SELECT name FROM namespaces WHERE name = ?", ("test_ns",)
            ).fetchone()
            assert row is not None
            assert row[0] == "test_ns"
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # 5. Newer DB version rejected safely
    # ------------------------------------------------------------------
    def test_newer_db_rejected(self, tmp_path):
        db_path = tmp_path / "newer.db"
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute("PRAGMA user_version = 999")
            conn.commit()

            with pytest.raises(RuntimeError) as exc_info:
                apply_migrations(conn)

            assert "999" in str(exc_info.value)
            assert (
                "newer" in str(exc_info.value).lower() or "supported" in str(exc_info.value).lower()
            )
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # 6. Failed migration rolls back transaction
    # ------------------------------------------------------------------
    def test_failed_migration_rolls_back(self, tmp_path, monkeypatch):
        db_path = tmp_path / "rollback.db"
        conn = sqlite3.connect(str(db_path))
        try:
            # Start at v0 so migrations will attempt to run
            # Monkeypatch a future migration to always fail
            original_migrations = dict(MIGRATIONS)

            def _bomb(conn):
                raise RuntimeError("simulated migration failure")

            # Only inject the bomb if we can add a fake v3
            monkeypatch.setitem(MIGRATIONS, 3, _bomb)
            monkeypatch.setattr(schema_migrations, "LATEST_SCHEMA_VERSION", 3)

            with pytest.raises(RuntimeError, match="simulated migration failure"):
                apply_migrations(conn)

            # user_version should NOT have advanced to 3
            version_row = conn.execute("PRAGMA user_version").fetchone()
            assert version_row[0] < 3
        finally:
            conn.close()
