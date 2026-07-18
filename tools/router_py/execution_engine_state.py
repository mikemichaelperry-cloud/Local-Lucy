#!/usr/bin/env python3
"""State persistence layer extracted from ExecutionEngine.

Handles dual-write to SQLite (via StateManager) and legacy .env files,
plus file-locking for safe concurrent access.

Additionally writes HMI-facing JSON state files:
  - last_request_result.json
  - last_route.json
  - request_history.jsonl
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import os
import re
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
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
        # In-memory cache of request IDs we've seen in this process.
        # Eliminates O(n) full-file scans for history dedup after warmup.
        self._history_id_cache: set[str] = set()

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

                        backoff_ms = backoff_base_ms * (2**attempt) * (2.5 if attempt > 0 else 1)
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

    # ------------------------------------------------------------------
    # Public write entry point
    # ------------------------------------------------------------------

    def write_state(
        self,
        route: RoutingDecision,
        result: ExecutionResult,
        context: dict[str, Any],
    ) -> None:
        """Write state to SQLite (if enabled)."""
        if self.use_sqlite_state:
            try:
                self._write_state_to_sqlite(route, result, context)
                self._logger.debug("State written to SQLite successfully")
            except Exception as e:
                self._logger.error(f"SQLite state write failed: {e}")

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
            question = _redact_pii(context.get("question", ""))
            route_data = {
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
                    "request_id": context.get("request_id", ""),
                },
            }

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

            outcome_data = {
                "success": result.status == "completed",
                "duration_ms": result.execution_time_ms,
                "result": outcome_meta,
                "error_message": _redact_pii(result.error_message or ""),
            }

            # Use atomic batch write to halve WAL fsyncs vs separate transactions
            if hasattr(self.state_manager, "write_batch"):
                self.state_manager.write_batch(route_data, outcome_data)
            else:
                # Fallback for older StateManager versions
                self.state_manager.write_route(route_data)
                self.state_manager.write_outcome(outcome_data)
            self._logger.info("State written to SQLite")
        except Exception as e:
            self._logger.error(f"SQLite state write failed: {e}")
            raise

    # ------------------------------------------------------------------
    # HMI-facing JSON state files
    # ------------------------------------------------------------------

    def write_json_state_files(
        self,
        route: RoutingDecision,
        result: ExecutionResult,
        context: dict[str, Any],
    ) -> None:
        """Write HMI-facing JSON state files in the same schema as runtime_request.py.

        This makes the Python router publish the same live status contract
        that the HMI already understands, without changing HMI code.
        """
        try:
            payload = self._build_json_payload(route, result, context)
            ui_state_dir = self._resolve_ui_state_dir()
            ui_state_dir.mkdir(parents=True, exist_ok=True)

            # 1. last_request_result.json
            result_file = ui_state_dir / "last_request_result.json"
            self._write_json_atomic(result_file, payload, prefix=".last_request_result.")

            # 2. last_route.json
            route_snapshot = self._build_route_snapshot_payload(payload)
            route_file = ui_state_dir / "last_route.json"
            self._write_json_atomic(route_file, route_snapshot, prefix=".last_route.")

            # 3. request_history.jsonl
            history_file = ui_state_dir / "request_history.jsonl"
            self._append_history_entry(history_file, payload)
        except Exception as e:
            self._logger.warning(f"Failed to write JSON state files: {e}")

    # -- Path helpers --

    def _resolve_ui_state_dir(self) -> Path:
        """Return the UI state directory (same logic as runtime_request.py)."""
        raw = os.environ.get("LUCY_UI_STATE_DIR", "").strip()
        if raw:
            return Path(raw).expanduser()
        # Fallback: same default as runtime_request.py
        home = Path.home()
        workspace_home = (
            home.parent if home.name in {".codex-api-home", ".codex-plus-home"} else home
        )
        return workspace_home / ".codex-api-home" / "lucy" / "runtime-v10" / "state"

    # -- Payload builder --

    def _build_json_payload(
        self,
        route: RoutingDecision,
        result: ExecutionResult,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Build a payload dict matching runtime_request.py's schema."""
        question = _redact_pii(context.get("question", ""))
        session_id = str(context.get("session_id", "") or "").strip()
        request_id = str(context.get("request_id", "") or "").strip()
        if not request_id:
            request_id = self._make_request_id()

        # Control state: best-effort from context + env fallback
        control_state = self._build_control_state(context)

        # Compute UTC timestamp once per payload (Phase 3E)
        utc_now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Route block
        route_block: dict[str, Any] = {
            "mode": result.route or route.route,
            "selected_route": result.route or route.route,
            "requested_mode": "",
            "final_mode": result.route or route.route,
            "intent_family": route.intent_family or "",
            "evidence_mode": route.evidence_mode or "",
            "evidence_mode_reason": route.evidence_reason or "",
            "evidence_mode_selection": "",
            "authority_basis": "",
            "winning_signal": "",
            "query": question,
            "reason": route.policy_reason or "router_classifier_mapper",
            "session_id": session_id,
            "utc": utc_now,
            "provider": result.provider or route.provider or "",
        }

        # Outcome block
        metadata = result.metadata or {}

        # Derive human-readable answer path for HMI display
        _route = result.route or route.route or "LOCAL"
        _trust = metadata.get("trust_class", "local")
        if _route in ("AUGMENTED", "EVIDENCE") or _trust == "evidence_backed":
            _answer_path = "Evidence-backed answer"
        elif _route == "CLARIFY":
            _answer_path = "Clarification requested"
        elif _route == "SELF_REVIEW":
            _answer_path = "Self-review answer"
        elif _route == "NEWS":
            _answer_path = "News (RSS)"
        elif _route == "TIME":
            _answer_path = "Time lookup"
        elif _route == "WEATHER":
            _answer_path = "Weather lookup"
        else:
            _answer_path = "Local answer"
        outcome_block: dict[str, Any] = {
            "action_hint": metadata.get("action_hint", ""),
            "requested_mode": "",
            "final_mode": result.route,
            "answer_class": "",
            "provider_authorization": "not_applicable",
            "operator_trust_label": metadata.get("trust_class", "local"),
            "operator_answer_path": _answer_path,
            "operator_note": "",
            "fallback_used": "true" if metadata.get("fallback_used") else "false",
            "fallback_reason": metadata.get("fallback_reason", ""),
            "trust_class": metadata.get("trust_class", "local"),
            "intent_family": route.intent_family or "",
            "evidence_mode": route.evidence_mode or "",
            "evidence_mode_reason": route.evidence_reason or "",
            "evidence_mode_selection": "",
            "augmented_allowed": "",
            "augmented_provider": "",
            "augmented_provider_selected": "",
            "augmented_provider_used": result.provider
            if result.route in {"AUGMENTED", "EVIDENCE"}
            else "none",
            "augmented_provider_usage_class": result.provider_usage_class or "local",
            "augmented_provider_call_reason": metadata.get("augmented_provider_call_reason", ""),
            "augmented_provider_status": metadata.get("augmented_provider_status", ""),
            "ANSWER_BASIS": metadata.get("ANSWER_BASIS", ""),
            "LIVE_FETCH_STATUS": metadata.get("LIVE_FETCH_STATUS", ""),
            "CONFIDENCE": metadata.get("CONFIDENCE", ""),
            "DEGRADED_REASON": metadata.get("DEGRADED_REASON", ""),
            "augmented_provider_error_reason": "",
            "augmented_provider_selection_reason": "",
            "augmented_provider_selection_query": "",
            "augmented_provider_selection_rule": "",
            "augmented_provider_cost_notice": "",
            "augmented_paid_provider_invoked": "true"
            if result.provider_usage_class == "paid" and result.route == "AUGMENTED"
            else "false",
            "augmentation_policy": control_state.get("augmentation_policy", ""),
            "augmented_direct_request": metadata.get("augmented_direct_request", ""),
            "unverified_context_used": "",
            "unverified_context_class": "",
            "unverified_context_title": "",
            "unverified_context_url": "",
            "primary_outcome_code": "",
            "primary_trust_class": "",
            "recovery_attempted": "",
            "recovery_used": "",
            "recovery_eligible": "",
            "recovery_lane": "",
            "augmented_behavior_shape": "",
            "augmented_clarification_required": "",
            "augmented_answer_contract": {},
            "self_review_request": "",
            "self_review_mode": "",
            "self_review_targets": "",
            "self_review_target_count": "",
            "evidence_created": "",
            "outcome_code": result.outcome_code,
            "rc": 0,
            "utc": utc_now,
        }

        # Authority block
        authority_block = self._build_authority_payload()

        return {
            "accepted": True,
            "authority": authority_block,
            "completed_at": utc_now,
            "control_state": control_state,
            "error": result.error_message or "",
            "outcome": outcome_block,
            "request_id": request_id,
            "request_text": question,
            "response_text": result.response_text or "",
            "route": route_block,
            "status": result.status,
        }

    def _build_control_state(self, context: dict[str, Any]) -> dict[str, str]:
        """Build control_state dict from context + environment fallbacks."""

        # Map boolean flags to on/off strings
        def _toggle(val: Any) -> str:
            if val in (True, "1", "on", "yes"):
                return "on"
            if val in (False, "0", "off", "no", ""):
                return "off"
            return str(val) if val else "off"

        mode = str(
            context.get("mode", "") or os.environ.get("LUCY_ROUTE_CONTROL_MODE", "auto")
        ).strip()
        memory = _toggle(context.get("memory_enabled", os.environ.get("LUCY_SESSION_MEMORY", "0")))
        evidence = _toggle(
            context.get("evidence_enabled", os.environ.get("LUCY_EVIDENCE_ENABLED", "0"))
        )
        voice = _toggle(os.environ.get("LUCY_VOICE_ENABLED", "0"))
        augmentation_policy = str(
            context.get("augmentation_policy", "")
            or os.environ.get("LUCY_AUGMENTATION_POLICY", "disabled")
        ).strip()
        augmented_provider = str(
            context.get("augmented_provider", "")
            or os.environ.get("LUCY_AUGMENTED_PROVIDER", "wikipedia")
        ).strip()
        model = str(context.get("model", "") or os.environ.get("LUCY_MODEL", "local-lucy")).strip()
        profile = str(os.environ.get("LUCY_RUNTIME_PROFILE", "lucy-v10")).strip()

        return {
            "mode": mode,
            "memory": memory,
            "evidence": evidence,
            "voice": voice,
            "augmentation_policy": augmentation_policy,
            "augmented_provider": augmented_provider,
            "model": model,
            "profile": profile,
        }

    def _build_authority_payload(self) -> dict[str, Any]:
        """Build authority block matching runtime_request.py schema."""
        # Resolve paths using same logic as runtime_request.py
        home = Path.home()
        workspace_home = (
            home.parent if home.name in {".codex-api-home", ".codex-plus-home"} else home
        )
        authority_root = Path(
            os.environ.get("LUCY_RUNTIME_AUTHORITY_ROOT", str(Path(__file__).resolve().parents[2]))
        ).expanduser()
        runtime_namespace = workspace_home / ".codex-api-home" / "lucy" / "runtime-v10"
        legacy_root = workspace_home / "lucy" / "runtime-v10"
        return {
            "active_root": str(authority_root),
            "authority_root": str(authority_root),
            "runtime_namespace_root": str(runtime_namespace),
            "legacy_runtime_namespace_root": str(legacy_root),
            "legacy_runtime_namespace_present": legacy_root.exists(),
            "legacy_runtime_namespace_status": (
                "same"
                if runtime_namespace.resolve() == legacy_root.resolve()
                else "stale_parallel_tree_present"
                if legacy_root.exists()
                else "absent"
            ),
        }

    def _build_route_snapshot_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Build last_route.json snapshot — delegates to shared payload_builders."""
        from router_py.payload_builders import build_route_snapshot_payload

        snapshot = build_route_snapshot_payload(payload)
        # Ensure authority is populated if missing from payload
        if not snapshot.get("authority"):
            snapshot["authority"] = self._build_authority_payload()
        # Ensure updated_at is set
        if not snapshot.get("updated_at"):
            snapshot["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return snapshot

    def _build_history_entry(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Build a history entry — delegates to shared payload_builders."""
        from router_py.payload_builders import build_history_entry

        return build_history_entry(payload)

    # -- Atomic I/O helpers --

    def _write_json_atomic(self, path: Path, data: dict[str, Any], *, prefix: str) -> None:
        """Write JSON atomically with file locking."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._file_lock(path):
            tmp = tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=path.parent, delete=False, prefix=prefix, suffix=".tmp"
            )
            try:
                json.dump(data, tmp, indent=2, sort_keys=True)
                tmp.write("\n")
                tmp.close()
                os.replace(tmp.name, path)
            except Exception:
                try:
                    Path(tmp.name).unlink(missing_ok=True)
                except Exception:
                    pass
                raise

    def _append_history_entry(self, history_file: Path, payload: dict[str, Any]) -> None:
        """Append entry to request_history.jsonl.

        NOTE: We no longer deduplicate by request_id.  The request_id now
        includes a nanosecond timestamp (main.py), so every execution is
        unique.  Dedup was originally needed because runtime_bridge.py
        used to write the same entry with the same deterministic ID.
        That dual-write has been removed; StateWriter is the sole writer.
        """
        entry = self._build_history_entry(payload)
        request_id = str(entry.get("request_id", "")).strip()
        if not request_id:
            return
        history_file.parent.mkdir(parents=True, exist_ok=True)
        with self._file_lock(history_file):
            with history_file.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, sort_keys=True))
                handle.write("\n")
            # Cache the ID we just wrote so future in-process checks are O(1)
            self._history_id_cache.add(request_id)
            # Prevent unbounded growth: trim to 2000 entries
            if len(self._history_id_cache) > 2000:
                self._history_id_cache = set(list(self._history_id_cache)[-1000:])

    def _history_contains_request_id(self, history_file: Path, request_id: str) -> bool:
        """Check if request_id already exists in history file.

        Fast path: in-memory set of IDs written by this process (O(1)).
        Fallback: tail-scan the last 50 lines of the file (catches IDs
        written by other processes without loading the entire file).
        """
        if request_id in self._history_id_cache:
            return True
        if not history_file.exists():
            return False
        try:
            # Tail-scan: only check the last 50 lines. If the file is
            # small, read it all; otherwise seek near the end.
            raw = history_file.read_text(encoding="utf-8")
            lines = raw.splitlines()
            # Check last 50 lines (or all if fewer)
            for raw_line in lines[-50:]:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    parsed = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if (
                    isinstance(parsed, dict)
                    and str(parsed.get("request_id", "")).strip() == request_id
                ):
                    # Populate cache so next check is instant
                    self._history_id_cache.add(request_id)
                    return True
        except OSError:
            pass
        return False

    def _make_request_id(self) -> str:
        """Generate a request ID matching runtime_request.py format."""
        return f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}-{os.getpid()}"

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
        """Verify SQLite and JSON file states match."""
        sqlite_route = self.read_last_route()
        json_route_file = self._resolve_ui_state_dir() / "last_route.json"
        file_strategy = None
        if json_route_file.exists():
            try:
                data = json.loads(json_route_file.read_text(encoding="utf-8"))
                file_strategy = data.get("current_route")
            except Exception:
                pass

        if sqlite_route and file_strategy:
            match = sqlite_route.get("strategy") == file_strategy
            if not match:
                self._logger.warning(
                    f"State mismatch between SQLite and JSON! "
                    f"SQLite: {sqlite_route.get('strategy')}, JSON: {file_strategy}"
                )
            else:
                self._logger.debug("State consistency verified: SQLite and JSON match")
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
                self.state_manager.write_outcome(
                    {
                        "success": outcome_code != "execution_error",
                        "duration_ms": execution_time_ms,
                        "result": {"outcome_code": outcome_code, "mode": mode},
                        "error_message": error_msg or "",
                    }
                )
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
    # Close / cleanup
