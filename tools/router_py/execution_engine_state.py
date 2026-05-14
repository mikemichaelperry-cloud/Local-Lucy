#!/usr/bin/env python3
"""State persistence layer extracted from ExecutionEngine.

Handles dual-write to SQLite (via StateManager) and legacy .env files,
plus file-locking for safe concurrent access.
"""

from __future__ import annotations

import fcntl
import logging
import re
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

from router_py.request_types import ExecutionResult, RoutingDecision
from router_py.state_manager import StateManager


# ---------------------------------------------------------------------------
# PII Redaction
# ---------------------------------------------------------------------------

_REDACT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "EMAIL"),
    (re.compile(r"(\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}"), "PHONE"),
    (re.compile(r"\b\d{3}[-.\s]?\d{2}[-.\s]?\d{4}\b"), "SSN"),
    (re.compile(r"\b(?:\d{4}[-.\s]?){3}\d{4}\b"), "CREDIT_CARD"),
]


def _redact_pii(text: str) -> str:
    """Scan text for common PII patterns and redact them."""
    if not text:
        return text
    for pattern, label in _REDACT_PATTERNS:
        text = pattern.sub(f"[REDACTED-{label}]", text)
    return text


class StateWriter:
    """Write and read execution state to SQLite and/or legacy .env files."""

    def __init__(
        self,
        state_dir: Path,
        state_manager: StateManager,
        logger: logging.Logger,
        use_sqlite_state: bool = True,
    ) -> None:
        self._state_dir = state_dir
        self.state_manager = state_manager
        self._logger = logger
        self.use_sqlite_state = use_sqlite_state

    # ------------------------------------------------------------------
    # File locking
    # ------------------------------------------------------------------

    @contextmanager
    def _file_lock(
        self,
        target_file: Path,
        max_retries: int = 3,
        backoff_base_ms: float = 10.0,
    ) -> Generator[None, None, None]:
        """Context manager for exclusive file locking with retry logic."""
        lock_file = Path(str(target_file) + ".lock")
        lock_fd = None
        lock_acquired = False

        try:
            lock_fd = open(lock_file, "a+")
            for attempt in range(max_retries + 1):
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    lock_acquired = True
                    break
                except (IOError, OSError) as e:
                    if attempt < max_retries:
                        import random

                        backoff_ms = (
                            backoff_base_ms * (2 ** attempt) * (2.5 if attempt > 0 else 1)
                        )
                        jitter_ms = random.uniform(0, 5)
                        sleep_time = (backoff_ms + jitter_ms) / 1000.0
                        self._logger.debug(
                            f"Lock attempt {attempt + 1} failed for {target_file}: {e}. "
                            f"Retrying in {sleep_time:.3f}s..."
                        )
                        time.sleep(sleep_time)
                    else:
                        self._logger.warning(
                            f"Failed to acquire lock for {target_file} after {max_retries + 1} attempts. "
                            f"Proceeding without lock (best-effort). Error: {e}"
                        )
            yield
        finally:
            if lock_fd:
                if lock_acquired:
                    try:
                        fcntl.flock(lock_fd, fcntl.LOCK_UN)
                    except (IOError, OSError) as e:
                        self._logger.warning(f"Error releasing lock for {target_file}: {e}")
                try:
                    lock_fd.close()
                except (IOError, OSError) as e:
                    self._logger.debug(f"Error closing lock file for {target_file}: {e}")

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    def get_state_file_paths(self) -> tuple[Path, Path]:
        """Return (route_file, outcome_file) for the current namespace."""
        route_file = self._state_dir / "last_route.env"
        outcome_file = self._state_dir / "last_outcome.env"
        return route_file, outcome_file

    # ------------------------------------------------------------------
    # Public write entry point
    # ------------------------------------------------------------------

    def write_state(
        self,
        route: RoutingDecision,
        result: ExecutionResult,
        context: dict[str, Any],
    ) -> None:
        """Dual-write to SQLite (if enabled) and legacy .env files."""
        if self.use_sqlite_state:
            try:
                self._write_state_to_sqlite(route, result, context)
                self._logger.debug("State written to SQLite successfully")
            except Exception as e:
                self._logger.error(f"SQLite state write failed: {e}")
        self._write_state_to_files(route, result, context)

    # ------------------------------------------------------------------
    # SQLite write
    # ------------------------------------------------------------------

    def _write_state_to_sqlite(
        self,
        route: RoutingDecision,
        result: ExecutionResult,
        context: dict[str, Any],
    ) -> None:
        try:
            question = _redact_pii(context.get("question", "")[:200])
            self.state_manager.write_route({
                "intent": context.get("intent", ""),
                "confidence": route.confidence,
                "strategy": route.route,
                "metadata": {
                    "question": question,
                    "provider": route.provider,
                    "provider_usage_class": route.provider_usage_class,
                    "is_medical_query": context.get("is_medical_query", False),
                    "final_mode": result.route,
                    "requested_mode": route.route,
                },
            })

            outcome_meta: dict[str, Any] = {
                "route": result.route,
                "provider": result.provider,
                "outcome_code": result.outcome_code,
                "trust_class": result.metadata.get("trust_class", "local"),
            }
            for key in (
                "memory_context_used",
                "memory_mode_used",
                "memory_top_score",
                "memory_session_injected",
                "memory_top_gap",
            ):
                if key in result.metadata:
                    outcome_meta[key] = result.metadata[key]

            self.state_manager.write_outcome({
                "success": result.status == "completed",
                "duration_ms": result.execution_time_ms,
                "result": outcome_meta,
                "error_message": _redact_pii(result.error_message or ""),
            })
            self._logger.info("State written to SQLite")
        except Exception as e:
            self._logger.error(f"SQLite state write failed: {e}")
            raise

    # ------------------------------------------------------------------
    # Legacy file write
    # ------------------------------------------------------------------

    def _write_state_to_files(
        self,
        route: RoutingDecision,
        result: ExecutionResult,
        context: dict[str, Any],
    ) -> None:
        question = _redact_pii(context.get("question", ""))
        resolved_question = _redact_pii(context.get("resolved_question", question))
        timestamp = int(time.time())
        route_file, outcome_file = self.get_state_file_paths()

        route_fields = [
            ("TIMESTAMP", str(timestamp)),
            ("FINAL_MODE", result.route),
            ("REQUESTED_MODE", route.route),
            ("ROUTE_REASON", "router_classifier_mapper"),
            ("ORIGINAL_QUESTION", question),
            ("RESOLVED_QUESTION", resolved_question),
            ("LOCAL_DIRECT_USED", "true" if result.metadata.get("local_direct_used") else "false"),
            ("LOCAL_DIRECT_FALLBACK", "true" if result.metadata.get("local_direct_fallback") else "false"),
            ("LOCAL_DIRECT_PATH", result.metadata.get("local_direct_path", "disabled")),
        ]

        outcome_fields = [
            ("TIMESTAMP", str(timestamp)),
            ("OUTCOME_CODE", result.outcome_code),
            ("FINAL_MODE", result.route),
            ("ROUTE_REASON", "router_classifier_mapper"),
            ("ORIGINAL_QUESTION", question),
            ("RESOLVED_QUESTION", resolved_question),
            ("FALLBACK_USED", "true" if result.metadata.get("fallback_used") else "false"),
            ("FALLBACK_REASON", result.metadata.get("fallback_reason", "none")),
            ("TRUST_CLASS", result.metadata.get("trust_class", "local")),
            ("AUGMENTED_PROVIDER_USED", result.provider if result.route == "AUGMENTED" else "none"),
            ("AUGMENTED_PROVIDER_USAGE_CLASS", result.provider_usage_class),
            ("EXECUTION_TIME_MS", str(result.execution_time_ms)),
            ("ROUTING_SIGNAL_MEDICAL_CONTEXT", "true" if context.get("is_medical_query") else "false"),
        ]

        for key in (
            "memory_context_used",
            "memory_mode_used",
            "memory_depth_used",
            "memory_top_score",
            "memory_session_injected",
            "memory_top_gap",
        ):
            if key in result.metadata:
                outcome_fields.append((key.upper(), result.metadata[key]))

        # Write last_route.env
        try:
            route_file.parent.mkdir(parents=True, exist_ok=True)
            route_content = "\n".join(f"{k}={v}" for k, v in route_fields) + "\n"
            with self._file_lock(route_file):
                route_file.write_text(route_content, encoding="utf-8")
        except Exception as e:
            self._logger.warning(f"Failed to write last_route.env: {e}")
            try:
                route_file.write_text(route_content, encoding="utf-8")
            except Exception as e2:
                self._logger.error(f"Unprotected write also failed: {e2}")

        # Write last_outcome.env
        try:
            outcome_file.parent.mkdir(parents=True, exist_ok=True)
            outcome_content = "\n".join(f"{k}={v}" for k, v in outcome_fields) + "\n"
            with self._file_lock(outcome_file):
                outcome_file.write_text(outcome_content, encoding="utf-8")
        except Exception as e:
            self._logger.warning(f"Failed to write last_outcome.env: {e}")
            try:
                outcome_file.write_text(outcome_content, encoding="utf-8")
            except Exception as e2:
                self._logger.error(f"Unprotected write also failed: {e2}")

    # ------------------------------------------------------------------
    # SQLite read
    # ------------------------------------------------------------------

    def read_last_route(self) -> dict | None:
        return self.state_manager.read_last_route()

    def read_last_outcome(self) -> dict | None:
        return self.state_manager.read_last_outcome()

    # ------------------------------------------------------------------
    # Consistency check (dual-write transition helper)
    # ------------------------------------------------------------------

    def verify_consistency(self) -> bool:
        sqlite_route = self.read_last_route()
        route_file, _ = self.get_state_file_paths()
        file_strategy = None
        if route_file.exists():
            file_strategy = self._read_state_field(route_file, "FINAL_MODE")

        if sqlite_route and file_strategy:
            match = sqlite_route.get("strategy") == file_strategy
            if not match:
                self._logger.warning(
                    f"State mismatch between SQLite and files! "
                    f"SQLite: {sqlite_route.get('strategy')}, File: {file_strategy}"
                )
            else:
                self._logger.debug("State consistency verified: SQLite and files match")
            return match

        if sqlite_route or file_strategy:
            self._logger.warning("Cannot verify consistency: only one state source available")
            return False

        return True

    # ------------------------------------------------------------------
    # Terminal outcome (early-exit paths)
    # ------------------------------------------------------------------

    def record_terminal_outcome(
        self,
        outcome_code: str,
        mode: str,
        error_msg: str | None = None,
        execution_time_ms: int = 0,
    ) -> None:
        if self.use_sqlite_state:
            try:
                self.state_manager.write_outcome({
                    "success": outcome_code != "execution_error",
                    "duration_ms": execution_time_ms,
                    "result": {"outcome_code": outcome_code, "mode": mode},
                    "error_message": error_msg or "",
                })
                self._logger.debug("Terminal outcome recorded in SQLite")
            except Exception as e:
                self._logger.error(f"Failed to record terminal outcome in SQLite: {e}")

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def close(self) -> None:
        try:
            self.state_manager.close()
            self._logger.debug("StateManager connection closed")
        except Exception as e:
            self._logger.warning(f"Error closing StateManager: {e}")

    # ------------------------------------------------------------------
    # Field read helper
    # ------------------------------------------------------------------

    def _read_state_field(self, state_file: Path, field: str) -> str | None:
        if not state_file.exists():
            return None
        try:
            with self._file_lock(state_file):
                content = state_file.read_text(encoding="utf-8")
                for line in content.splitlines():
                    if line.startswith(f"{field}="):
                        return line[len(field) + 1 :].strip()
        except Exception:
            try:
                content = state_file.read_text(encoding="utf-8")
                for line in content.splitlines():
                    if line.startswith(f"{field}="):
                        return line[len(field) + 1 :].strip()
            except Exception:
                pass
        return None
