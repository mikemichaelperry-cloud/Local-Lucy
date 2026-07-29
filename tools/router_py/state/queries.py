#!/usr/bin/env python3
"""Low-level SQLite query operations for Local Lucy state."""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from typing import List, Optional

logger = logging.getLogger(__name__)


def ensure_namespace(conn: sqlite3.Connection, namespace: str) -> int:
    """Ensure namespace exists and return its ID.

    Args:
        conn: SQLite connection.
        namespace: Namespace name to ensure.

    Returns:
        int: Namespace ID for foreign key references.
    """
    cursor = conn.execute("INSERT OR IGNORE INTO namespaces (name) VALUES (?)", (namespace,))
    cursor = conn.execute("SELECT id FROM namespaces WHERE name = ?", (namespace,))
    row = cursor.fetchone()
    namespace_id = row[0]
    logger.debug(f"Using namespace '{namespace}' with ID {namespace_id}")
    return namespace_id


def write_route(conn: sqlite3.Connection, namespace_id: int, route_data: dict) -> bool:
    """Write a route decision to the database.

    Args:
        conn: SQLite connection.
        namespace_id: Namespace ID.
        route_data: Dictionary containing:
            - intent (str): The detected intent
            - confidence (float): Confidence score (0.0-1.0)
            - strategy (str, optional): Routing strategy used
            - metadata (dict, optional): Additional routing context

    Returns:
        bool: True if write succeeded, False otherwise.
    """
    try:
        metadata = json.dumps(route_data.get("metadata", {}))
        conn.execute(
            """
            INSERT INTO routes (namespace_id, intent, confidence, strategy, metadata)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                namespace_id,
                route_data["intent"],
                route_data["confidence"],
                route_data.get("strategy"),
                metadata,
            ),
        )
        logger.info(f"Route written: {route_data['intent']} ({route_data['confidence']})")
        return True
    except Exception as e:
        logger.error(f"Failed to write route: {e}")
        return False


def read_last_route(conn: sqlite3.Connection, namespace_id: int) -> Optional[dict]:
    """Read the most recent route for a namespace.

    Args:
        conn: SQLite connection.
        namespace_id: Namespace ID.

    Returns:
        dict: Route data including id, intent, confidence, etc.
        None: If no routes exist in this namespace.
    """
    try:
        cursor = conn.execute(
            """
            SELECT id, intent, confidence, strategy, metadata, created_at
            FROM routes
            WHERE namespace_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (namespace_id,),
        )
        row = cursor.fetchone()
        if row:
            return {
                "id": row["id"],
                "intent": row["intent"],
                "confidence": row["confidence"],
                "strategy": row["strategy"],
                "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
                "created_at": row["created_at"],
            }
        return None
    except Exception as e:
        logger.error(f"Failed to read last route: {e}")
        return None


def read_routes(
    conn: sqlite3.Connection,
    namespace_id: int,
    limit: int = 10,
    offset: int = 0,
    since: Optional[float] = None,
) -> List[dict]:
    """Read multiple routes with pagination.

    Args:
        conn: SQLite connection.
        namespace_id: Namespace ID.
        limit: Maximum number of routes to return.
        offset: Number of routes to skip.
        since: Unix timestamp to filter routes after this time.

    Returns:
        List of route dictionaries.
    """
    try:
        if since:
            cursor = conn.execute(
                """
                SELECT id, intent, confidence, strategy, metadata, created_at
                FROM routes
                WHERE namespace_id = ? AND created_at > datetime(?, 'unixepoch')
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (namespace_id, since, limit, offset),
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
                (namespace_id, limit, offset),
            )

        routes = []
        for row in cursor.fetchall():
            routes.append(
                {
                    "id": row["id"],
                    "intent": row["intent"],
                    "confidence": row["confidence"],
                    "strategy": row["strategy"],
                    "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
                    "created_at": row["created_at"],
                }
            )
        return routes
    except Exception as e:
        logger.error(f"Failed to read routes: {e}")
        return []


def write_outcome(conn: sqlite3.Connection, namespace_id: int, outcome_data: dict) -> bool:
    """Write an execution outcome to the database.

    Args:
        conn: SQLite connection.
        namespace_id: Namespace ID.
        outcome_data: Dictionary containing:
            - route_id (int, optional): Associated route ID
            - success (bool): Whether execution succeeded
            - duration_ms (int, optional): Execution time in milliseconds
            - result (dict, optional): Result data
            - error_message (str, optional): Error if failed

    Returns:
        bool: True if write succeeded, False otherwise.
    """
    try:
        result_json = json.dumps(outcome_data.get("result", {}))
        conn.execute(
            """
            INSERT INTO outcomes (namespace_id, route_id, success, duration_ms, result, error_message)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                namespace_id,
                outcome_data.get("route_id"),
                outcome_data["success"],
                outcome_data.get("duration_ms"),
                result_json,
                outcome_data.get("error_message"),
            ),
        )
        logger.info(f"Outcome written: success={outcome_data['success']}")
        return True
    except Exception as e:
        logger.error(f"Failed to write outcome: {e}")
        return False


def write_batch(
    conn: sqlite3.Connection, namespace_id: int, route_data: dict, outcome_data: dict
) -> bool:
    """Atomically write both route and outcome in a single transaction.

    Args:
        conn: SQLite connection.
        namespace_id: Namespace ID.
        route_data: Same as write_route().
        outcome_data: Same as write_outcome().

    Returns:
        bool: True if both writes succeeded, False otherwise.
    """
    try:
        # Route insert
        metadata = json.dumps(route_data.get("metadata", {}))
        conn.execute(
            """
            INSERT INTO routes (namespace_id, intent, confidence, strategy, metadata)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                namespace_id,
                route_data["intent"],
                route_data["confidence"],
                route_data.get("strategy"),
                metadata,
            ),
        )
        # Outcome insert
        result_json = json.dumps(outcome_data.get("result", {}))
        conn.execute(
            """
            INSERT INTO outcomes (namespace_id, route_id, success, duration_ms, result, error_message)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                namespace_id,
                outcome_data.get("route_id"),
                outcome_data["success"],
                outcome_data.get("duration_ms"),
                result_json,
                outcome_data.get("error_message"),
            ),
        )
        logger.info(
            f"Batch written: route={route_data['intent']} outcome={outcome_data['success']}"
        )
        return True
    except Exception as e:
        logger.error(f"Failed to write batch: {e}")
        return False


def read_last_outcome(conn: sqlite3.Connection, namespace_id: int) -> Optional[dict]:
    """Read the most recent outcome for a namespace.

    Args:
        conn: SQLite connection.
        namespace_id: Namespace ID.

    Returns:
        dict: Outcome data including id, success, duration, etc.
        None: If no outcomes exist in this namespace.
    """
    try:
        cursor = conn.execute(
            """
            SELECT id, route_id, success, duration_ms, result, error_message, created_at
            FROM outcomes
            WHERE namespace_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (namespace_id,),
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
                "created_at": row["created_at"],
            }
        return None
    except Exception as e:
        logger.error(f"Failed to read last outcome: {e}")
        return None


def read_outcomes(
    conn: sqlite3.Connection,
    namespace_id: int,
    success_only: bool = False,
    limit: int = 10,
    since: Optional[float] = None,
) -> List[dict]:
    """Read outcomes with optional filtering.

    Args:
        conn: SQLite connection.
        namespace_id: Namespace ID.
        success_only: If True, only return successful outcomes.
        limit: Maximum number of outcomes to return.
        since: Unix timestamp to filter outcomes after this time.

    Returns:
        List of outcome dictionaries.
    """
    try:
        query = """
            SELECT id, route_id, success, duration_ms, result, error_message, created_at
            FROM outcomes
            WHERE namespace_id = ?
        """
        params = [namespace_id]

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
            outcomes.append(
                {
                    "id": row["id"],
                    "route_id": row["route_id"],
                    "success": bool(row["success"]),
                    "duration_ms": row["duration_ms"],
                    "result": json.loads(row["result"]) if row["result"] else {},
                    "error_message": row["error_message"],
                    "created_at": row["created_at"],
                }
            )
        return outcomes
    except Exception as e:
        logger.error(f"Failed to read outcomes: {e}")
        return []


def write_session(
    conn: sqlite3.Connection,
    namespace_id: int,
    session_key: str,
    data: dict,
    ttl_seconds: Optional[int] = None,
) -> bool:
    """Write or update session data.

    Args:
        conn: SQLite connection.
        namespace_id: Namespace ID.
        session_key: Unique identifier for the session.
        data: Session data dictionary.
        ttl_seconds: Time-to-live in seconds (None for no expiration).

    Returns:
        bool: True if write succeeded.
    """
    try:
        expires_at = None
        if ttl_seconds is not None:
            expires_at = time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime(time.time() + ttl_seconds)
            )

        data_json = json.dumps(data)
        conn.execute(
            """
            INSERT INTO sessions (namespace_id, session_key, data, expires_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(namespace_id, session_key) DO UPDATE SET
                data = excluded.data,
                expires_at = excluded.expires_at,
                updated_at = CURRENT_TIMESTAMP
            """,
            (namespace_id, session_key, data_json, expires_at),
        )
        logger.debug(f"Session written: {session_key}")
        return True
    except Exception as e:
        logger.error(f"Failed to write session: {e}")
        return False


def read_session(conn: sqlite3.Connection, namespace_id: int, session_key: str) -> Optional[dict]:
    """Read session data if not expired.

    Args:
        conn: SQLite connection.
        namespace_id: Namespace ID.
        session_key: Session identifier.

    Returns:
        dict: Session data if found and not expired.
        None: If not found or expired.
    """
    try:
        cursor = conn.execute(
            """
            SELECT data, expires_at FROM sessions
            WHERE session_key = ? AND namespace_id = ?
            """,
            (session_key, namespace_id),
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


def delete_session(conn: sqlite3.Connection, namespace_id: int, session_key: str) -> bool:
    """Delete a session.

    Args:
        conn: SQLite connection.
        namespace_id: Namespace ID.
        session_key: Session identifier.

    Returns:
        bool: True if deleted, False if not found.
    """
    try:
        cursor = conn.execute(
            "DELETE FROM sessions WHERE session_key = ? AND namespace_id = ?",
            (session_key, namespace_id),
        )
        deleted = cursor.rowcount > 0
        if deleted:
            logger.debug(f"Session deleted: {session_key}")
        return deleted
    except Exception as e:
        logger.error(f"Failed to delete session: {e}")
        return False


def acquire_lock(conn: sqlite3.Connection, namespace_id: int, lock_name: str, owner: str) -> bool:
    """Attempt to acquire a distributed lock within a single transaction.

    This is a single-shot acquisition attempt; the polling loop lives in the
    caller (manager.py).

    Args:
        conn: SQLite connection.
        namespace_id: Namespace ID.
        lock_name: Name of the lock to acquire.
        owner: Owner identifier for the lock.

    Returns:
        bool: True if lock acquired, False if already held.
    """
    # Clean up expired locks
    conn.execute("DELETE FROM locks WHERE expires_at < datetime('now')")

    # Try to acquire lock
    expires_at = time.strftime(
        "%Y-%m-%d %H:%M:%S",
        time.localtime(time.time() + 60),  # 60 second default expiration
    )

    try:
        conn.execute(
            """
            INSERT INTO locks (namespace_id, lock_name, owner, expires_at)
            VALUES (?, ?, ?, ?)
            """,
            (namespace_id, lock_name, owner, expires_at),
        )
        logger.debug(f"Lock acquired: {lock_name} by {owner}")
        return True
    except sqlite3.IntegrityError:
        # Lock already held
        pass

    return False


def release_lock(conn: sqlite3.Connection, namespace_id: int, lock_name: str, owner: str) -> bool:
    """Release a previously acquired lock.

    Args:
        conn: SQLite connection.
        namespace_id: Namespace ID.
        lock_name: Name of the lock to release.
        owner: Owner identifier for the lock.

    Returns:
        bool: True if lock was released, False if not owned.
    """
    try:
        cursor = conn.execute(
            """
            DELETE FROM locks
            WHERE namespace_id = ? AND lock_name = ? AND owner = ?
            """,
            (namespace_id, lock_name, owner),
        )
        released = cursor.rowcount > 0
        if released:
            logger.debug(f"Lock released: {lock_name}")
        return released
    except Exception as e:
        logger.error(f"Failed to release lock: {e}")
        return False


def is_locked(conn: sqlite3.Connection, namespace_id: int, lock_name: str) -> bool:
    """Check if a lock is currently held (and not expired).

    Args:
        conn: SQLite connection.
        namespace_id: Namespace ID.
        lock_name: Name of the lock to check.

    Returns:
        bool: True if lock exists and is valid.
    """
    try:
        # Clean up expired locks first
        conn.execute("DELETE FROM locks WHERE expires_at < datetime('now')")
        conn.commit()

        cursor = conn.execute(
            """
            SELECT 1 FROM locks
            WHERE namespace_id = ? AND lock_name = ?
            """,
            (namespace_id, lock_name),
        )
        return cursor.fetchone() is not None
    except Exception as e:
        logger.error(f"Failed to check lock status: {e}")
        return False


def record_telemetry(
    conn: sqlite3.Connection, namespace_id: int, event_type: str, event_data: dict
) -> bool:
    """Record a telemetry event.

    Args:
        conn: SQLite connection.
        namespace_id: Namespace ID.
        event_type: Type/category of event.
        event_data: Event-specific data dictionary.

    Returns:
        bool: True if recorded successfully.
    """
    try:
        data_json = json.dumps(event_data)
        conn.execute(
            """
            INSERT INTO telemetry (namespace_id, event_type, event_data)
            VALUES (?, ?, ?)
            """,
            (namespace_id, event_type, data_json),
        )
        logger.debug(f"Telemetry recorded: {event_type}")
        return True
    except Exception as e:
        logger.error(f"Failed to record telemetry: {e}")
        return False


def get_telemetry_summary(
    conn: sqlite3.Connection,
    namespace_id: int,
    namespace: str,
    event_type: Optional[str] = None,
    since: Optional[float] = None,
) -> dict:
    """Get summary statistics from telemetry.

    Args:
        conn: SQLite connection.
        namespace_id: Namespace ID.
        namespace: Namespace name to include in the result.
        event_type: Filter by event type.
        since: Unix timestamp to filter events after.

    Returns:
        dict: Summary statistics.
    """
    try:
        # Build query
        where_clause = "WHERE namespace_id = ?"
        params = [namespace_id]

        if event_type:
            where_clause += " AND event_type = ?"
            params.append(event_type)
        if since:
            where_clause += " AND created_at > datetime(?, 'unixepoch')"
            params.append(since)

        # Get total count
        cursor = conn.execute(f"SELECT COUNT(*) FROM telemetry {where_clause}", params)
        total_count = cursor.fetchone()[0]

        # Get event type breakdown
        cursor = conn.execute(
            f"""
            SELECT event_type, COUNT(*) as count
            FROM telemetry
            {where_clause}
            GROUP BY event_type
            """,
            params,
        )
        breakdown = {row["event_type"]: row["count"] for row in cursor.fetchall()}

        return {
            "total_count": total_count,
            "event_breakdown": breakdown,
            "namespace": namespace,
        }
    except Exception as e:
        logger.error(f"Failed to get telemetry summary: {e}")
        return {"total_count": 0, "event_breakdown": {}, "namespace": namespace}
