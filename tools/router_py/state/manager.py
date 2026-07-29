#!/usr/bin/env python3
"""SQLite-backed state manager for Local Lucy."""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from router_py.state import queries, schema

logger = logging.getLogger(__name__)


class StateManager:
    """
    SQLite-backed state manager with namespace support.

    Provides thread-safe access to routing state, outcomes, sessions,
    and telemetry with transaction safety and connection pooling.

    Attributes:
        namespace: The namespace for isolation (default: "default")
        db_path: Path to the SQLite database file
        _local: Thread-local storage for connections
        _lock: threading.RLock for thread safety
    """

    def __init__(self, namespace: str = "default"):
        """
        Initialize StateManager with the given namespace.

        Args:
            namespace: Namespace for data isolation. Different namespaces
                      have completely separate data sets.
        """
        self.namespace = namespace
        self._local = threading.local()
        self._lock = threading.RLock()

        # Determine database path from environment or use default
        router_root = Path(__file__).parent.parent.parent
        self.db_path = Path(
            os.environ.get("LUCY_STATE_DB", router_root / "state" / "lucy_state.db")
        )

        # Ensure state directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Initialize schema and namespace
        self._init_schema()
        self._namespace_id = self._ensure_namespace()

        # Harden DB file permissions (production readiness)
        try:
            os.chmod(self.db_path, 0o600)
        except OSError:
            pass

    # ---------------------------------------------------------------------
    # Connection Management
    # ---------------------------------------------------------------------

    def _get_connection(self) -> sqlite3.Connection:
        """
        Get thread-local database connection.

        Returns:
            sqlite3.Connection: Thread-local connection with row factory
        """
        if not hasattr(self._local, "connection") or self._local.connection is None:
            conn = sqlite3.connect(str(self.db_path), check_same_thread=False, timeout=30.0)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.connection = conn
            logger.debug(f"Created new connection for thread {threading.current_thread().name}")
        return self._local.connection

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        """
        Context manager for database transactions.

        Automatically commits on success, rolls back on exception.

        Yields:
            sqlite3.Connection: Connection for executing queries

        Example:
            >>> with self._transaction() as conn:
            ...     conn.execute("INSERT ...")
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            yield conn
            conn.commit()
            logger.debug("Transaction committed successfully")
        except Exception as e:
            conn.rollback()
            logger.error(f"Transaction rolled back due to error: {e}")
            raise

    # ---------------------------------------------------------------------
    # Schema & Namespace Management
    # ---------------------------------------------------------------------

    def _init_schema(self) -> None:
        """
        Initialize database schema via versioned migrations.

        Thread-safe, safe to call multiple times (idempotent).
        """
        with self._lock:
            conn = sqlite3.connect(str(self.db_path), timeout=30.0)
            try:
                version = schema.apply_migrations(conn)
                logger.info(f"Schema at version {version} at {self.db_path}")
            finally:
                conn.close()

    def _ensure_namespace(self) -> int:
        """
        Ensure namespace exists and return its ID.

        Returns:
            int: Namespace ID for foreign key references
        """
        with self._transaction() as conn:
            self._namespace_id = queries.ensure_namespace(conn, self.namespace)
        return self._namespace_id

    # ---------------------------------------------------------------------
    # Route Operations
    # ---------------------------------------------------------------------

    def write_route(self, route_data: dict) -> bool:
        """
        Write a route decision to the database.

        Args:
            route_data: Dictionary containing:
                - intent (str): The detected intent
                - confidence (float): Confidence score (0.0-1.0)
                - strategy (str, optional): Routing strategy used
                - metadata (dict, optional): Additional routing context

        Returns:
            bool: True if write succeeded, False otherwise
        """
        try:
            with self._transaction() as conn:
                return queries.write_route(conn, self._namespace_id, route_data)
        except Exception as e:
            logger.error(f"Failed to write route: {e}")
            return False

    def read_last_route(self) -> Optional[dict]:
        """
        Read the most recent route for this namespace.

        Returns:
            dict: Route data including id, intent, confidence, etc.
            None: If no routes exist in this namespace
        """
        try:
            conn = self._get_connection()
            return queries.read_last_route(conn, self._namespace_id)
        except Exception as e:
            logger.error(f"Failed to read last route: {e}")
            return None

    def read_routes(
        self, limit: int = 10, offset: int = 0, since: Optional[float] = None
    ) -> list[dict]:
        """
        Read multiple routes with pagination.

        Args:
            limit: Maximum number of routes to return
            offset: Number of routes to skip
            since: Unix timestamp to filter routes after this time

        Returns:
            List of route dictionaries
        """
        try:
            conn = self._get_connection()
            return queries.read_routes(conn, self._namespace_id, limit, offset, since)
        except Exception as e:
            logger.error(f"Failed to read routes: {e}")
            return []

    # ---------------------------------------------------------------------
    # Outcome Operations
    # ---------------------------------------------------------------------

    def write_outcome(self, outcome_data: dict) -> bool:
        """
        Write an execution outcome to the database.

        Args:
            outcome_data: Dictionary containing:
                - route_id (int, optional): Associated route ID
                - success (bool): Whether execution succeeded
                - duration_ms (int, optional): Execution time in milliseconds
                - result (dict, optional): Result data
                - error_message (str, optional): Error if failed

        Returns:
            bool: True if write succeeded, False otherwise
        """
        try:
            with self._transaction() as conn:
                return queries.write_outcome(conn, self._namespace_id, outcome_data)
        except Exception as e:
            logger.error(f"Failed to write outcome: {e}")
            return False

    def write_batch(self, route_data: dict, outcome_data: dict) -> bool:
        """
        Atomically write both route and outcome in a single transaction.

        Halves WAL fsyncs compared to calling write_route() + write_outcome()
        separately. Use this when both records are available at the same time.

        Args:
            route_data: Same as write_route()
            outcome_data: Same as write_outcome()

        Returns:
            bool: True if both writes succeeded, False otherwise
        """
        try:
            with self._transaction() as conn:
                return queries.write_batch(conn, self._namespace_id, route_data, outcome_data)
        except Exception as e:
            logger.error(f"Failed to write batch: {e}")
            return False

    def read_last_outcome(self) -> Optional[dict]:
        """
        Read the most recent outcome for this namespace.

        Returns:
            dict: Outcome data including id, success, duration, etc.
            None: If no outcomes exist in this namespace
        """
        try:
            conn = self._get_connection()
            return queries.read_last_outcome(conn, self._namespace_id)
        except Exception as e:
            logger.error(f"Failed to read last outcome: {e}")
            return None

    def read_outcomes(
        self, success_only: bool = False, limit: int = 10, since: Optional[float] = None
    ) -> list[dict]:
        """
        Read outcomes with optional filtering.

        Args:
            success_only: If True, only return successful outcomes
            limit: Maximum number of outcomes to return
            since: Unix timestamp to filter outcomes after this time

        Returns:
            List of outcome dictionaries
        """
        try:
            conn = self._get_connection()
            return queries.read_outcomes(conn, self._namespace_id, success_only, limit, since)
        except Exception as e:
            logger.error(f"Failed to read outcomes: {e}")
            return []

    # ---------------------------------------------------------------------
    # Session Operations
    # ---------------------------------------------------------------------

    def write_session(
        self, session_key: str, data: dict, ttl_seconds: Optional[int] = None
    ) -> bool:
        """
        Write or update session data.

        Args:
            session_key: Unique identifier for the session
            data: Session data dictionary
            ttl_seconds: Time-to-live in seconds (None for no expiration)

        Returns:
            bool: True if write succeeded
        """
        try:
            with self._transaction() as conn:
                return queries.write_session(conn, self._namespace_id, session_key, data, ttl_seconds)
        except Exception as e:
            logger.error(f"Failed to write session: {e}")
            return False

    def read_session(self, session_key: str) -> Optional[dict]:
        """
        Read session data if not expired.

        Args:
            session_key: Session identifier

        Returns:
            dict: Session data if found and not expired
            None: If not found or expired
        """
        try:
            conn = self._get_connection()
            return queries.read_session(conn, self._namespace_id, session_key)
        except Exception as e:
            logger.error(f"Failed to read session: {e}")
            return None

    def delete_session(self, session_key: str) -> bool:
        """
        Delete a session.

        Args:
            session_key: Session identifier

        Returns:
            bool: True if deleted, False if not found
        """
        try:
            with self._transaction() as conn:
                return queries.delete_session(conn, self._namespace_id, session_key)
        except Exception as e:
            logger.error(f"Failed to delete session: {e}")
            return False

    # ---------------------------------------------------------------------
    # Lock Operations
    # ---------------------------------------------------------------------

    def acquire_lock(self, lock_name: str, timeout: float = 5.0) -> bool:
        """
        Acquire a distributed lock.

        Uses database-backed locking with automatic expiration.
        Safe for use across multiple processes.

        Args:
            lock_name: Name of the lock to acquire
            timeout: Maximum seconds to wait for lock

        Returns:
            bool: True if lock acquired, False if timeout
        """
        owner = f"{os.getpid()}_{threading.current_thread().ident}"
        start_time = time.time()
        poll_interval = 0.1

        while time.time() - start_time < timeout:
            try:
                with self._transaction() as conn:
                    if queries.acquire_lock(conn, self._namespace_id, lock_name, owner):
                        return True
            except Exception as e:
                logger.error(f"Error acquiring lock: {e}")

            time.sleep(poll_interval)

        logger.warning(f"Lock acquisition timed out: {lock_name}")
        return False

    def release_lock(self, lock_name: str) -> bool:
        """
        Release a previously acquired lock.

        Args:
            lock_name: Name of the lock to release

        Returns:
            bool: True if lock was released, False if not owned
        """
        owner = f"{os.getpid()}_{threading.current_thread().ident}"
        try:
            with self._transaction() as conn:
                return queries.release_lock(conn, self._namespace_id, lock_name, owner)
        except Exception as e:
            logger.error(f"Failed to release lock: {e}")
            return False

    def is_locked(self, lock_name: str) -> bool:
        """
        Check if a lock is currently held (and not expired).

        Args:
            lock_name: Name of the lock to check

        Returns:
            bool: True if lock exists and is valid
        """
        try:
            conn = self._get_connection()
            return queries.is_locked(conn, self._namespace_id, lock_name)
        except Exception as e:
            logger.error(f"Failed to check lock status: {e}")
            return False

    # ---------------------------------------------------------------------
    # Telemetry Operations
    # ---------------------------------------------------------------------

    def record_telemetry(self, event_type: str, event_data: dict) -> bool:
        """
        Record a telemetry event.

        Args:
            event_type: Type/category of event
            event_data: Event-specific data dictionary

        Returns:
            bool: True if recorded successfully
        """
        try:
            with self._transaction() as conn:
                return queries.record_telemetry(conn, self._namespace_id, event_type, event_data)
        except Exception as e:
            logger.error(f"Failed to record telemetry: {e}")
            return False

    def get_telemetry_summary(
        self, event_type: Optional[str] = None, since: Optional[float] = None
    ) -> dict:
        """
        Get summary statistics from telemetry.

        Args:
            event_type: Filter by event type
            since: Unix timestamp to filter events after

        Returns:
            dict: Summary statistics
        """
        try:
            conn = self._get_connection()
            return queries.get_telemetry_summary(
                conn, self._namespace_id, self.namespace, event_type, since
            )
        except Exception as e:
            logger.error(f"Failed to get telemetry summary: {e}")
            return {"total_count": 0, "event_breakdown": {}, "namespace": self.namespace}

    # ---------------------------------------------------------------------
    # Utility Methods
    # ---------------------------------------------------------------------

    def close(self) -> None:
        """
        Close all database connections.

        Should be called on cleanup, though connections will be
        automatically closed when threads exit.
        """
        if hasattr(self._local, "connection") and self._local.connection:
            try:
                self._local.connection.close()
                self._local.connection = None
                logger.debug("Database connection closed")
            except Exception as e:
                logger.error(f"Error closing connection: {e}")

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - ensures cleanup."""
        self.close()

    def health_check(self) -> dict:
        """
        Perform health check on state manager.

        Returns:
            dict: Health status including:
                - connected: bool
                - tables: list of table names
                - namespace: current namespace
                - row_counts: approximate row counts per table
        """
        try:
            conn = self._get_connection()

            # Check connection
            cursor = conn.execute("SELECT 1")
            connected = cursor.fetchone() is not None

            # Get table names
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row["name"] for row in cursor.fetchall()]

            # Get row counts
            row_counts = {}
            for table in tables:
                try:
                    cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
                    row_counts[table] = cursor.fetchone()[0]
                except Exception:
                    row_counts[table] = -1

            return {
                "connected": connected,
                "tables": tables,
                "namespace": self.namespace,
                "namespace_id": self._namespace_id,
                "row_counts": row_counts,
                "db_path": str(self.db_path),
            }
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return {"connected": False, "error": str(e), "namespace": self.namespace}


def get_state_manager(namespace: str = "default") -> StateManager:
    """Factory function to get a StateManager instance."""
    return StateManager(namespace=namespace)
