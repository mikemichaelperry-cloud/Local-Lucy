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
        workspace_home = home.parent if home.name in {".codex-api-home", ".codex-plus-home"} else home
        return workspace_home / ".codex-api-home" / "lucy" / "runtime-v8" / "state"

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
            "utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

        # Outcome block
        metadata = result.metadata or {}
        outcome_block: dict[str, Any] = {
            "action_hint": metadata.get("action_hint", ""),
            "requested_mode": "",
            "final_mode": result.route,
            "answer_class": "",
            "provider_authorization": "not_applicable",
            "operator_trust_label": metadata.get("trust_class", "local"),
            "operator_answer_path": "unknown",
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
            "augmented_provider_used": result.provider if result.route == "AUGMENTED" else "none",
            "augmented_provider_usage_class": result.provider_usage_class or "local",
            "augmented_provider_call_reason": metadata.get("augmented_provider_call_reason", ""),
            "augmented_provider_status": metadata.get("augmented_provider_status", ""),
            "augmented_provider_error_reason": "",
            "augmented_provider_selection_reason": "",
            "augmented_provider_selection_query": "",
            "augmented_provider_selection_rule": "",
            "augmented_provider_cost_notice": "",
            "augmented_paid_provider_invoked": "true" if result.provider_usage_class == "paid" and result.route == "AUGMENTED" else "false",
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
            "utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

        # Authority block
        authority_block = self._build_authority_payload()

        return {
            "accepted": True,
            "authority": authority_block,
            "completed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
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

        mode = str(context.get("mode", "") or os.environ.get("LUCY_ROUTE_CONTROL_MODE", "auto")).strip()
        memory = _toggle(context.get("memory_enabled", os.environ.get("LUCY_SESSION_MEMORY", "0")))
        evidence = _toggle(context.get("evidence_enabled", os.environ.get("LUCY_EVIDENCE_ENABLED", "0")))
        voice = _toggle(os.environ.get("LUCY_VOICE_ENABLED", "0"))
        augmentation_policy = str(
            context.get("augmentation_policy", "")
            or os.environ.get("LUCY_AUGMENTATION_POLICY", "disabled")
        ).strip()
        augmented_provider = str(
            context.get("augmented_provider", "")
            or os.environ.get("LUCY_AUGMENTED_PROVIDER", "wikipedia")
        ).strip()
        model = str(
            context.get("model", "")
            or os.environ.get("LUCY_MODEL", "local-lucy")
        ).strip()
        profile = str(os.environ.get("LUCY_RUNTIME_PROFILE", "opt-experimental-v8-dev")).strip()

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
        workspace_home = home.parent if home.name in {".codex-api-home", ".codex-plus-home"} else home
        authority_root = Path(os.environ.get("LUCY_RUNTIME_AUTHORITY_ROOT", str(Path(__file__).resolve().parents[2]))).expanduser()
        runtime_namespace = workspace_home / ".codex-api-home" / "lucy" / "runtime-v8"
        legacy_root = workspace_home / "lucy" / "runtime-v8"
        return {
            "active_root": str(authority_root),
            "authority_root": str(authority_root),
            "runtime_namespace_root": str(runtime_namespace),
            "legacy_runtime_namespace_root": str(legacy_root),
            "legacy_runtime_namespace_present": legacy_root.exists(),
            "legacy_runtime_namespace_status": (
                "same" if runtime_namespace.resolve() == legacy_root.resolve()
                else "stale_parallel_tree_present" if legacy_root.exists()
                else "absent"
            ),
        }

    def _build_route_snapshot_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Build last_route.json snapshot matching runtime_request.py schema."""
        route = payload.get("route") if isinstance(payload.get("route"), dict) else {}
        outcome = payload.get("outcome") if isinstance(payload.get("outcome"), dict) else {}
        authority = payload.get("authority") if isinstance(payload.get("authority"), dict) else self._build_authority_payload()
        current_route = str(
            route.get("selected_route") or route.get("mode") or route.get("final_mode") or route.get("requested_mode") or ""
        ).strip()
        provider_used = str(
            outcome.get("augmented_provider_used")
            or outcome.get("augmented_provider")
            or outcome.get("augmented_provider_selected")
            or ""
        ).strip()
        trust_class = str(outcome.get("trust_class", "")).strip()
        source_type = self._determine_route_source_type(current_route, provider_used, trust_class)
        return {
            "current_route": current_route,
            "final_mode": str(route.get("final_mode", "")).strip(),
            "intent_family": str(route.get("intent_family", "")).strip(),
            "mode": str(route.get("mode", "")).strip(),
            "outcome_code": str(outcome.get("outcome_code", "")).strip(),
            "provider_used": provider_used or "none",
            "request_id": str(payload.get("request_id", "")).strip(),
            "route": current_route,
            "route_reason": str(route.get("reason", "")).strip(),
            "selected_route": str(route.get("selected_route", "")).strip(),
            "source": source_type,
            "source_type": source_type,
            "status": str(payload.get("status", "")).strip(),
            "answer_class": str(outcome.get("answer_class", "")).strip(),
            "provider_authorization": str(outcome.get("provider_authorization", "")).strip(),
            "operator_trust_label": str(outcome.get("operator_trust_label", "")).strip(),
            "operator_answer_path": str(outcome.get("operator_answer_path", "")).strip(),
            "trust_class": trust_class,
            "updated_at": str(payload.get("completed_at", "")).strip() or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "authority": authority if isinstance(authority, dict) else {},
        }

    def _determine_route_source_type(self, current_route: str, provider_used: str, trust_class: str) -> str:
        """Mirror of runtime_request.py:determine_route_source_type()."""
        route_label = current_route.strip().upper()
        provider_label = provider_used.strip().lower()
        trust_label = trust_class.strip().lower()
        if provider_label in {"openai", "grok", "wikipedia"}:
            return provider_label
        if route_label == "LOCAL":
            return "local"
        if route_label == "EVIDENCE":
            return "evidence"
        if route_label == "SELF_REVIEW":
            return "self_review"
        if trust_label:
            return trust_label
        return "unknown"

    def _build_history_entry(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Mirror of runtime_request.py:build_history_entry()."""
        control_state = payload.get("control_state")
        return {
            "authority": payload.get("authority", {}) if isinstance(payload.get("authority"), dict) else {},
            "completed_at": payload.get("completed_at", ""),
            "control_state": control_state if isinstance(control_state, dict) else {},
            "error": payload.get("error", ""),
            "outcome": payload.get("outcome", {}) if isinstance(payload.get("outcome"), dict) else {},
            "request_id": payload.get("request_id", ""),
            "request_text": payload.get("request_text", ""),
            "response_text": payload.get("response_text", ""),
            "route": payload.get("route", {}) if isinstance(payload.get("route"), dict) else {},
            "status": payload.get("status", ""),
        }

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
        """Append deduplicated entry to request_history.jsonl."""
        entry = self._build_history_entry(payload)
        request_id = str(entry.get("request_id", "")).strip()
        if not request_id:
            return
        history_file.parent.mkdir(parents=True, exist_ok=True)
        with self._file_lock(history_file):
            if self._history_contains_request_id(history_file, request_id):
                return
            with history_file.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, sort_keys=True))
                handle.write("\n")

    def _history_contains_request_id(self, history_file: Path, request_id: str) -> bool:
        """Check if request_id already exists in history file."""
        if not history_file.exists():
            return False
        try:
            for raw_line in history_file.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    parsed = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict) and str(parsed.get("request_id", "")).strip() == request_id:
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
