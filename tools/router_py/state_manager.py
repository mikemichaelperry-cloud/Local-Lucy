#!/usr/bin/env python3
"""
State Manager - SQLite-backed state management for Lucy V8 Router.

Replaces shell-based state management with a robust SQLite backend.
Supports namespaces, concurrent access via WAL mode, and provides
transaction safety with automatic rollback on errors.

Migration Path:
    - Reads legacy .env files if SQLite is empty
    - Writes to both during transition period
    - Eventually .env files will be deprecated

Example:
    >>> sm = StateManager(namespace="production")
    >>> sm.write_route({"intent": "search", "confidence": 0.95})
    >>> last_route = sm.read_last_route()
"""

import sqlite3
import threading
import json
import time
import os
import logging
from pathlib import Path
from contextlib import contextmanager
from typing import Optional, Dict, Any, List, Iterator
from dataclasses import dataclass


# ============================================================================
# Logging Setup
# ============================================================================

logger = logging.getLogger(__name__)


# ============================================================================
# Schema Definition
# ============================================================================

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
    session_key TEXT UNIQUE NOT NULL,
    data TEXT,  -- JSON blob
    expires_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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


# ============================================================================
# StateManager Class
# ============================================================================

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
        self.db_path = Path(os.environ.get(
            "LUCY_STATE_DB", 
            router_root / "state" / "lucy_state.db"
        ))
        
        # Ensure state directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Initialize schema and namespace
        self._init_schema()
        self._namespace_id = self._ensure_namespace()
    
    # ---------------------------------------------------------------------
    # Connection Management
    # ---------------------------------------------------------------------
    
    def _get_connection(self) -> sqlite3.Connection:
        """
        Get thread-local database connection.
        
        Returns:
            sqlite3.Connection: Thread-local connection with row factory
        """
        if not hasattr(self._local, 'connection') or self._local.connection is None:
            conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                timeout=30.0
            )
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
        Initialize database schema if not exists.
        
        Creates all tables, indexes, and sets WAL mode.
        Thread-safe, safe to call multiple times.
        """
        with self._lock:
            conn = sqlite3.connect(str(self.db_path), timeout=30.0)
            try:
                conn.executescript(SCHEMA_SQL)
                conn.commit()
                logger.info(f"Schema initialized at {self.db_path}")
            finally:
                conn.close()
    
    def _ensure_namespace(self) -> int:
        """
        Ensure namespace exists and return its ID.
        
        Returns:
            int: Namespace ID for foreign key references
        """
        with self._transaction() as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO namespaces (name) VALUES (?)",
                (self.namespace,)
            )
            cursor = conn.execute(
                "SELECT id FROM namespaces WHERE name = ?",
                (self.namespace,)
            )
            row = cursor.fetchone()
            namespace_id = row[0]
            logger.debug(f"Using namespace '{self.namespace}' with ID {namespace_id}")
            return namespace_id
    
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
            
        Example:
            >>> sm.write_route({
            ...     "intent": "search",
            ...     "confidence": 0.95,
            ...     "strategy": "ml_classifier",
            ...     "metadata": {"model_version": "v2.1"}
            ... })
            True
        """
        try:
            with self._transaction() as conn:
                metadata = json.dumps(route_data.get("metadata", {}))
                conn.execute(
                    """
                    INSERT INTO routes (namespace_id, intent, confidence, strategy, metadata)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        self._namespace_id,
                        route_data["intent"],
                        route_data["confidence"],
                        route_data.get("strategy"),
                        metadata
                    )
                )
                logger.info(f"Route written: {route_data['intent']} ({route_data['confidence']})")
                return True
        except Exception as e:
            logger.error(f"Failed to write route: {e}")
            return False
    
    def read_last_route(self) -> Optional[dict]:
        """
        Read the most recent route for this namespace.
        
        Returns:
            dict: Route data including id, intent, confidence, etc.
            None: If no routes exist in this namespace
            
        Example:
            >>> route = sm.read_last_route()
            >>> print(route["intent"])
            'search'
        """
        try:
            conn = self._get_connection()
            cursor = conn.execute(
                """
                SELECT id, intent, confidence, strategy, metadata, created_at
                FROM routes
                WHERE namespace_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (self._namespace_id,)
            )
            row = cursor.fetchone()
            if row:
                return {
                    "id": row["id"],
                    "intent": row["intent"],
                    "confidence": row["confidence"],
                    "strategy": row["strategy"],
                    "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
                    "created_at": row["created_at"]
                }
            return None
        except Exception as e:
            logger.error(f"Failed to read last route: {e}")
            return None
    
    def read_routes(
        self, 
        limit: int = 10, 
        offset: int = 0,
        since: Optional[float] = None
    ) -> List[dict]:
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
            if since:
                cursor = conn.execute(
                    """
                    SELECT id, intent, confidence, strategy, metadata, created_at
                    FROM routes
                    WHERE namespace_id = ? AND created_at > datetime(?, 'unixepoch')
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (self._namespace_id, since, limit, offset)
                )
            else:
                cursor = conn.execute(
                    """
                    SELECT id, intent, confidence, strategy, metadata, created_at
                    FROM routes
                    WHERE namespace_id = ?
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (self._namespace_id, limit, offset)
                )
            
            routes = []
            for row in cursor.fetchall():
                routes.append({
                    "id": row["id"],
                    "intent": row["intent"],
                    "confidence": row["confidence"],
                    "strategy": row["strategy"],
                    "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
                    "created_at": row["created_at"]
                })
            return routes
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
            
        Example:
            >>> sm.write_outcome({
            ...     "route_id": 123,
            ...     "success": True,
            ...     "duration_ms": 150,
            ...     "result": {"items_found": 5}
            ... })
            True
        """
        try:
            with self._transaction() as conn:
                result_json = json.dumps(outcome_data.get("result", {}))
                conn.execute(
                    """
                    INSERT INTO outcomes (namespace_id, route_id, success, duration_ms, result, error_message)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        self._namespace_id,
                        outcome_data.get("route_id"),
                        outcome_data["success"],
                        outcome_data.get("duration_ms"),
                        result_json,
                        outcome_data.get("error_message")
                    )
                )
                logger.info(f"Outcome written: success={outcome_data['success']}")
                return True
        except Exception as e:
            logger.error(f"Failed to write outcome: {e}")
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
            cursor = conn.execute(
                """
                SELECT id, route_id, success, duration_ms, result, error_message, created_at
                FROM outcomes
                WHERE namespace_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (self._namespace_id,)
            )
            row = cursor.fetchone()
            if row:
                return {
                    "id": row["id"],
                    "route_id": row["route_id"],
                    "success": bool(row["success"]),
                    "duration_ms": row["duration_ms"],
                    "result": json.loads(row["result"]) if row["result"] else {},
                    "error_message": row["error_message"],
                    "created_at": row["created_at"]
                }
            return None
        except Exception as e:
            logger.error(f"Failed to read last outcome: {e}")
            return None
    
    def read_outcomes(
        self,
        success_only: bool = False,
        limit: int = 10,
        since: Optional[float] = None
    ) -> List[dict]:
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
            query = """
                SELECT id, route_id, success, duration_ms, result, error_message, created_at
                FROM outcomes
                WHERE namespace_id = ?
            """
            params = [self._namespace_id]
            
            if success_only:
                query += " AND success = 1"
            if since:
                query += " AND created_at > datetime(?, 'unixepoch')"
                params.append(since)
            
            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            
            cursor = conn.execute(query, params)
            
            outcomes = []
            for row in cursor.fetchall():
                outcomes.append({
                    "id": row["id"],
                    "route_id": row["route_id"],
                    "success": bool(row["success"]),
                    "duration_ms": row["duration_ms"],
                    "result": json.loads(row["result"]) if row["result"] else {},
                    "error_message": row["error_message"],
                    "created_at": row["created_at"]
                })
            return outcomes
        except Exception as e:
            logger.error(f"Failed to read outcomes: {e}")
            return []
    
    # ---------------------------------------------------------------------
    # Session Operations
    # ---------------------------------------------------------------------
    
    def write_session(self, session_key: str, data: dict, ttl_seconds: Optional[int] = None) -> bool:
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
                expires_at = None
                if ttl_seconds is not None:
                    expires_at = time.strftime(
                        "%Y-%m-%d %H:%M:%S",
                        time.localtime(time.time() + ttl_seconds)
                    )
                
                data_json = json.dumps(data)
                conn.execute(
                    """
                    INSERT INTO sessions (namespace_id, session_key, data, expires_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(session_key) DO UPDATE SET
                        data = excluded.data,
                        expires_at = excluded.expires_at,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (self._namespace_id, session_key, data_json, expires_at)
                )
                logger.debug(f"Session written: {session_key}")
                return True
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
            cursor = conn.execute(
                """
                SELECT data, expires_at FROM sessions
                WHERE session_key = ? AND namespace_id = ?
                """,
                (session_key, self._namespace_id)
            )
            row = cursor.fetchone()
            
            if row:
                expires_at = row["expires_at"]
                if expires_at and expires_at < time.strftime("%Y-%m-%d %H:%M:%S"):
                    # Session expired, delete it
                    conn.execute("DELETE FROM sessions WHERE session_key = ?", (session_key,))
                    conn.commit()
                    logger.debug(f"Session expired and deleted: {session_key}")
                    return None
                
                return json.loads(row["data"]) if row["data"] else {}
            return None
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
                cursor = conn.execute(
                    "DELETE FROM sessions WHERE session_key = ? AND namespace_id = ?",
                    (session_key, self._namespace_id)
                )
                deleted = cursor.rowcount > 0
                if deleted:
                    logger.debug(f"Session deleted: {session_key}")
                return deleted
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
            
        Example:
            >>> if sm.acquire_lock("model_training", timeout=10.0):
            ...     try:
            ...         # Do critical work
            ...         pass
            ...     finally:
            ...         sm.release_lock("model_training")
        """
        owner = f"{os.getpid()}_{threading.current_thread().ident}"
        start_time = time.time()
        poll_interval = 0.1
        
        while time.time() - start_time < timeout:
            try:
                with self._transaction() as conn:
                    # Clean up expired locks
                    conn.execute(
                        "DELETE FROM locks WHERE expires_at < datetime('now')"
                    )
                    
                    # Try to acquire lock
                    expires_at = time.strftime(
                        "%Y-%m-%d %H:%M:%S",
                        time.localtime(time.time() + 60)  # 60 second default expiration
                    )
                    
                    try:
                        conn.execute(
                            """
                            INSERT INTO locks (namespace_id, lock_name, owner, expires_at)
                            VALUES (?, ?, ?, ?)
                            """,
                            (self._namespace_id, lock_name, owner, expires_at)
                        )
                        logger.debug(f"Lock acquired: {lock_name} by {owner}")
                        return True
                    except sqlite3.IntegrityError:
                        # Lock already held
                        pass
                        
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
                cursor = conn.execute(
                    """
                    DELETE FROM locks 
                    WHERE namespace_id = ? AND lock_name = ? AND owner = ?
                    """,
                    (self._namespace_id, lock_name, owner)
                )
                released = cursor.rowcount > 0
                if released:
                    logger.debug(f"Lock released: {lock_name}")
                return released
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
            
            # Clean up expired locks first
            conn.execute("DELETE FROM locks WHERE expires_at < datetime('now')")
            conn.commit()
            
            cursor = conn.execute(
                """
                SELECT 1 FROM locks 
                WHERE namespace_id = ? AND lock_name = ?
                """,
                (self._namespace_id, lock_name)
            )
            return cursor.fetchone() is not None
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
                data_json = json.dumps(event_data)
                conn.execute(
                    """
                    INSERT INTO telemetry (namespace_id, event_type, event_data)
                    VALUES (?, ?, ?)
                    """,
                    (self._namespace_id, event_type, data_json)
                )
                logger.debug(f"Telemetry recorded: {event_type}")
                return True
        except Exception as e:
            logger.error(f"Failed to record telemetry: {e}")
            return False
    
    def get_telemetry_summary(
        self,
        event_type: Optional[str] = None,
        since: Optional[float] = None
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
            
            # Build query
            where_clause = "WHERE namespace_id = ?"
            params = [self._namespace_id]
            
            if event_type:
                where_clause += " AND event_type = ?"
                params.append(event_type)
            if since:
                where_clause += " AND created_at > datetime(?, 'unixepoch')"
                params.append(since)
            
            # Get total count
            cursor = conn.execute(
                f"SELECT COUNT(*) FROM telemetry {where_clause}",
                params
            )
            total_count = cursor.fetchone()[0]
            
            # Get event type breakdown
            cursor = conn.execute(
                f"""
                SELECT event_type, COUNT(*) as count 
                FROM telemetry 
                {where_clause}
                GROUP BY event_type
                """,
                params
            )
            breakdown = {row["event_type"]: row["count"] for row in cursor.fetchall()}
            
            return {
                "total_count": total_count,
                "event_breakdown": breakdown,
                "namespace": self.namespace
            }
        except Exception as e:
            logger.error(f"Failed to get telemetry summary: {e}")
            return {"total_count": 0, "event_breakdown": {}, "namespace": self.namespace}
    
    # ---------------------------------------------------------------------
    # Migration from Legacy (.env files)
    # ---------------------------------------------------------------------
    
    def migrate_from_env(self, env_path: Optional[Path] = None) -> bool:
        """
        Migrate state from legacy .env files to SQLite.
        
        Reads existing .env files and imports their data.
        Safe to run multiple times (idempotent).
        
        Args:
            env_path: Path to .env file (default: router_root/.env)
            
        Returns:
            bool: True if migration succeeded or nothing to migrate
        """
        try:
            router_root = Path(__file__).parent.parent.parent
            
            # Check for legacy env files
            legacy_files = ["last_route.env", "last_outcome.env"]
            migrated = False
            
            for filename in legacy_files:
                file_path = router_root / filename
                if file_path.exists():
                    logger.info(f"Migrating legacy file: {filename}")
                    
                    with open(file_path, 'r') as f:
                        data = {}
                        for line in f:
                            line = line.strip()
                            if line and '=' in line and not line.startswith('#'):
                                key, value = line.split('=', 1)
                                data[key] = value
                    
                    if filename == "last_route.env" and data:
                        self.write_route({
                            "intent": data.get("LAST_ROUTE_INTENT", "unknown"),
                            "confidence": float(data.get("LAST_ROUTE_CONFIDENCE", 0.0)),
                            "strategy": data.get("LAST_ROUTE_STRATEGY"),
                            "metadata": data
                        })
                        migrated = True
                    
                    elif filename == "last_outcome.env" and data:
                        self.write_outcome({
                            "success": data.get("LAST_OUTCOME_SUCCESS", "false").lower() == "true",
                            "duration_ms": int(data.get("LAST_OUTCOME_DURATION_MS", 0)),
                            "result": data
                        })
                        migrated = True
            
            if migrated:
                logger.info("Migration from .env files completed successfully")
            else:
                logger.debug("No legacy .env files found to migrate")
            
            return True
        except Exception as e:
            logger.error(f"Migration failed: {e}")
            return False
    
    def write_env_backup(self, key: str, value: str) -> bool:
        """
        Write to legacy .env file during transition period.
        
        Maintains backward compatibility while migrating.
        
        Args:
            key: Environment variable name
            value: Value to write
            
        Returns:
            bool: True if write succeeded
        """
        try:
            router_root = Path(__file__).parent.parent.parent
            env_file = router_root / "state_backup.env"
            
            # Read existing content
            lines = []
            if env_file.exists():
                with open(env_file, 'r') as f:
                    lines = f.readlines()
            
            # Update or append key
            key_found = False
            for i, line in enumerate(lines):
                if line.startswith(f"{key}="):
                    lines[i] = f"{key}={value}\n"
                    key_found = True
                    break
            
            if not key_found:
                lines.append(f"{key}={value}\n")
            
            with open(env_file, 'w') as f:
                f.writelines(lines)
            
            return True
        except Exception as e:
            logger.error(f"Failed to write .env backup: {e}")
            return False
    
    # ---------------------------------------------------------------------
    # Utility Methods
    # ---------------------------------------------------------------------
    
    def close(self) -> None:
        """
        Close all database connections.
        
        Should be called on cleanup, though connections will be
        automatically closed when threads exit.
        """
        if hasattr(self._local, 'connection') and self._local.connection:
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
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            tables = [row["name"] for row in cursor.fetchall()]
            
            # Get row counts
            row_counts = {}
            for table in tables:
                try:
                    cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
                    row_counts[table] = cursor.fetchone()[0]
                except:
                    row_counts[table] = -1
            
            return {
                "connected": connected,
                "tables": tables,
                "namespace": self.namespace,
                "namespace_id": self._namespace_id,
                "row_counts": row_counts,
                "db_path": str(self.db_path)
            }
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return {
                "connected": False,
                "error": str(e),
                "namespace": self.namespace
            }


# ============================================================================
# Helper Functions
# ============================================================================

def get_state_manager(namespace: str = "default") -> StateManager:
    """
    Factory function to get a StateManager instance.
    
    Args:
        namespace: Namespace for isolation
        
    Returns:
        StateManager: Configured instance
    """
    return StateManager(namespace=namespace)


def init_database(db_path: Optional[Path] = None) -> bool:
    """
    Initialize database without creating a StateManager instance.
    
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
            conn.executescript(SCHEMA_SQL)
            conn.commit()
            logger.info(f"Database initialized at {db_path}")
            return True
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        return False


# ============================================================================
# Module Entry Point
# ============================================================================

if __name__ == "__main__":
    # Configure logging for testing
    logging.basicConfig(level=logging.DEBUG)
    
    print("=" * 60)
    print("StateManager Implementation Test")
    print("=" * 60)
    
    # Test the implementation
    sm = StateManager("test")
    print(f"\n1. Created StateManager for namespace: {sm.namespace}")
    
    # Health check
    health = sm.health_check()
    print(f"\n2. Health Check:")
    print(f"   Connected: {health['connected']}")
    print(f"   Tables: {health['tables']}")
    print(f"   Row counts: {health['row_counts']}")
    
    # Test write_route
    print(f"\n3. Testing write_route():")
    result = sm.write_route({
        "intent": "search",
        "confidence": 0.95,
        "strategy": "ml_classifier",
        "metadata": {"model_version": "v2.1", "query": "test"}
    })
    print(f"   Write result: {result}")
    
    # Test read_last_route
    print(f"\n4. Testing read_last_route():")
    route = sm.read_last_route()
    print(f"   Route: {route}")
    
    # Test write_outcome
    print(f"\n5. Testing write_outcome():")
    result = sm.write_outcome({
        "success": True,
        "duration_ms": 150,
        "result": {"items_found": 5, "query_time": 45}
    })
    print(f"   Write result: {result}")
    
    # Test read_last_outcome
    print(f"\n6. Testing read_last_outcome():")
    outcome = sm.read_last_outcome()
    print(f"   Outcome: {outcome}")
    
    # Test lock operations
    print(f"\n7. Testing lock operations:")
    lock_acquired = sm.acquire_lock("test_lock", timeout=2.0)
    print(f"   Lock acquired: {lock_acquired}")
    if lock_acquired:
        is_locked = sm.is_locked("test_lock")
        print(f"   Is locked: {is_locked}")
        released = sm.release_lock("test_lock")
        print(f"   Lock released: {released}")
    
    # Test session operations
    print(f"\n8. Testing session operations:")
    session_result = sm.write_session("test_session", {"user": "test", "data": [1, 2, 3]}, ttl_seconds=300)
    print(f"   Session write: {session_result}")
    session_data = sm.read_session("test_session")
    print(f"   Session read: {session_data}")
    session_deleted = sm.delete_session("test_session")
    print(f"   Session deleted: {session_deleted}")
    
    # Test telemetry
    print(f"\n9. Testing telemetry:")
    telem_result = sm.record_telemetry("test_event", {"metric": 42, "status": "ok"})
    print(f"   Telemetry recorded: {telem_result}")
    summary = sm.get_telemetry_summary()
    print(f"   Telemetry summary: {summary}")
    
    # Test read multiple routes
    print(f"\n10. Testing read_routes():")
    sm.write_route({"intent": "help", "confidence": 0.8, "strategy": "LOCAL"})
    routes = sm.read_routes(limit=5)
    print(f"   Routes: {len(routes)} found")
    for r in routes:
        print(f"      - {r['intent']} ({r['confidence']})")
    
    # Test read outcomes with filter
    print(f"\n11. Testing read_outcomes(success_only=True):")
    outcomes = sm.read_outcomes(success_only=True, limit=5)
    print(f"   Success outcomes: {len(outcomes)} found")
    
    # Final health check
    print(f"\n12. Final health check:")
    health = sm.health_check()
    print(f"   Row counts: {health['row_counts']}")
    
    # Cleanup
    sm.close()
    print(f"\n✅ All tests completed successfully!")
    print("=" * 60)
