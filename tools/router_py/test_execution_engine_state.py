#!/usr/bin/env python3
"""
Unit tests for execution_engine_state.StateWriter.

Covers:
- File path resolution
- Legacy .env file writes (all field types, memory telemetry, error paths)
- SQLite writes via mocked StateManager
- Dual-write consistency verification
- Terminal outcome recording
- Field read-back
- File-locking behavior
- Close/cleanup

Run with:
    cd /home/mike/lucy-v8 && source ui-v8/.venv/bin/activate
    python3 -m pytest tools/router_py/test_execution_engine_state.py -v
"""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, call

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest

from router_py.execution_engine_state import StateWriter
from router_py.request_types import ExecutionResult, RoutingDecision


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_state_dir():
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


@pytest.fixture
def mock_logger():
    return logging.getLogger("test_state_writer")


@pytest.fixture
def mock_state_manager():
    sm = MagicMock()
    sm.read_last_route.return_value = None
    sm.read_last_outcome.return_value = None
    return sm


@pytest.fixture
def writer(tmp_state_dir, mock_state_manager, mock_logger):
    return StateWriter(
        state_dir=tmp_state_dir,
        state_manager=mock_state_manager,
        logger=mock_logger,
        use_sqlite_state=True,
    )


@pytest.fixture
def sample_route():
    return RoutingDecision(
        route="LOCAL",
        mode="AUTO",
        intent_family="local_answer",
        confidence=0.95,
        provider="local",
        provider_usage_class="local",
        evidence_mode="",
    )


@pytest.fixture
def sample_result():
    return ExecutionResult(
        status="completed",
        outcome_code="answered",
        route="LOCAL",
        provider="local",
        provider_usage_class="local",
        response_text="The answer is 42.",
        execution_time_ms=123,
        metadata={
            "trust_class": "local",
            "fallback_used": False,
            "fallback_reason": "none",
            "local_direct_used": True,
            "local_direct_fallback": False,
            "local_direct_path": "python_native",
        },
    )


@pytest.fixture
def sample_context():
    return {
        "question": "What is the meaning of life?",
        "resolved_question": "What is the meaning of life?",
        "intent": "local_answer",
        "is_medical_query": False,
    }


# ---------------------------------------------------------------------------
# SQLite writes
# ---------------------------------------------------------------------------


class TestSQLiteWrites:
    def test_sqlite_route_write(self, writer, mock_state_manager, sample_route, sample_result, sample_context):
        writer._write_state_to_sqlite(sample_route, sample_result, sample_context)
        assert mock_state_manager.write_route.called
        args, _ = mock_state_manager.write_route.call_args
        payload = args[0]
        assert payload["intent"] == "local_answer"
        assert payload["confidence"] == 0.95
        assert payload["strategy"] == "LOCAL"
        assert payload["metadata"]["question"] == "What is the meaning of life?"
        assert payload["metadata"]["provider"] == "local"
        assert payload["metadata"]["final_mode"] == "LOCAL"

    def test_sqlite_outcome_write(self, writer, mock_state_manager, sample_route, sample_result, sample_context):
        writer._write_state_to_sqlite(sample_route, sample_result, sample_context)
        assert mock_state_manager.write_outcome.called
        args, _ = mock_state_manager.write_outcome.call_args
        payload = args[0]
        assert payload["success"] is True
        assert payload["duration_ms"] == 123
        assert payload["result"]["route"] == "LOCAL"
        assert payload["result"]["outcome_code"] == "answered"
        assert payload["error_message"] == ""

    def test_sqlite_outcome_includes_memory_telemetry(self, writer, mock_state_manager, sample_route, sample_context):
        result = ExecutionResult(
            status="completed", outcome_code="answered", route="LOCAL",
            provider="local", provider_usage_class="local",
            response_text="Answer.", execution_time_ms=100,
            metadata={
                "trust_class": "local",
                "memory_context_used": "session",
                "memory_mode_used": "recall",
                "memory_top_score": "0.87",
                "memory_session_injected": "true",
                "memory_top_gap": "0.12",
            },
        )
        writer._write_state_to_sqlite(sample_route, result, sample_context)
        args, _ = mock_state_manager.write_outcome.call_args
        result_meta = args[0]["result"]
        assert result_meta["memory_context_used"] == "session"
        assert result_meta["memory_mode_used"] == "recall"
        assert result_meta["memory_top_score"] == "0.87"
        assert result_meta["memory_session_injected"] == "true"
        assert result_meta["memory_top_gap"] == "0.12"

    def test_sqlite_failure_logs_error(self, writer, mock_state_manager, sample_route, sample_result, sample_context, caplog):
        mock_state_manager.write_route.side_effect = RuntimeError("disk full")
        with caplog.at_level(logging.ERROR, logger="test_state_writer"):
            with pytest.raises(RuntimeError, match="disk full"):
                writer._write_state_to_sqlite(sample_route, sample_result, sample_context)
        assert "disk full" in caplog.text

    def test_sqlite_disabled_skips_write(self, mock_state_manager, mock_logger, sample_route, sample_result, sample_context):
        writer = StateWriter(
            state_dir=Path("/tmp"),
            state_manager=mock_state_manager,
            logger=mock_logger,
            use_sqlite_state=False,
        )
        writer.write_state(sample_route, sample_result, sample_context)
        assert not mock_state_manager.write_route.called
        assert not mock_state_manager.write_outcome.called


# ---------------------------------------------------------------------------
# Dual-write entry point
# ---------------------------------------------------------------------------


class TestWriteState:
    def test_sqlite_write_invoked(self, writer, mock_state_manager, sample_route, sample_result, sample_context):
        """write_state() must call SQLite when use_sqlite_state=True."""
        writer.write_state(sample_route, sample_result, sample_context)
        assert mock_state_manager.write_route.called
        assert mock_state_manager.write_outcome.called

    def test_sqlite_error_logged(self, writer, mock_state_manager, sample_route, sample_result, sample_context, caplog):
        """SQLite errors must be logged but not raise."""
        mock_state_manager.write_route.side_effect = RuntimeError("disk full")
        with caplog.at_level(logging.ERROR, logger="test_state_writer"):
            writer.write_state(sample_route, sample_result, sample_context)
        assert "disk full" in caplog.text


# ---------------------------------------------------------------------------
# Read-back helpers
# ---------------------------------------------------------------------------


class TestReadBack:
    def test_read_last_route_delegates(self, writer, mock_state_manager):
        mock_state_manager.read_last_route.return_value = {"strategy": "TIME"}
        assert writer.read_last_route() == {"strategy": "TIME"}

    def test_read_last_outcome_delegates(self, writer, mock_state_manager):
        mock_state_manager.read_last_outcome.return_value = {"success": True}
        assert writer.read_last_outcome() == {"success": True}


# ---------------------------------------------------------------------------
# Consistency verification
# ---------------------------------------------------------------------------


class TestConsistency:
    def _write_json_route(self, writer, route: str = "LOCAL") -> None:
        """Helper: write a JSON route file for consistency checks."""
        ui_dir = writer._resolve_ui_state_dir()
        ui_dir.mkdir(parents=True, exist_ok=True)
        (ui_dir / "last_route.json").write_text(
            json.dumps({"current_route": route, "outcome_code": "answered"}),
            encoding="utf-8",
        )

    def test_consistent_states(self, writer, mock_state_manager, tmp_state_dir, monkeypatch):
        monkeypatch.setenv("LUCY_UI_STATE_DIR", str(tmp_state_dir))
        self._write_json_route(writer, "LOCAL")
        mock_state_manager.read_last_route.return_value = {"strategy": "LOCAL"}
        assert writer.verify_consistency() is True

    def test_inconsistent_states(self, writer, mock_state_manager, tmp_state_dir, monkeypatch):
        monkeypatch.setenv("LUCY_UI_STATE_DIR", str(tmp_state_dir))
        self._write_json_route(writer, "LOCAL")
        mock_state_manager.read_last_route.return_value = {"strategy": "AUGMENTED"}
        assert writer.verify_consistency() is False

    def test_only_sqlite_available(self, writer, mock_state_manager, tmp_state_dir, monkeypatch):
        monkeypatch.setenv("LUCY_UI_STATE_DIR", str(tmp_state_dir))
        mock_state_manager.read_last_route.return_value = {"strategy": "LOCAL"}
        assert writer.verify_consistency() is False

    def test_only_json_available(self, writer, mock_state_manager, tmp_state_dir, monkeypatch):
        monkeypatch.setenv("LUCY_UI_STATE_DIR", str(tmp_state_dir))
        self._write_json_route(writer, "LOCAL")
        mock_state_manager.read_last_route.return_value = None
        assert writer.verify_consistency() is False

    def test_neither_available(self, writer, tmp_state_dir, monkeypatch):
        monkeypatch.setenv("LUCY_UI_STATE_DIR", str(tmp_state_dir))
        assert writer.verify_consistency() is True


# ---------------------------------------------------------------------------
# Terminal outcome
# ---------------------------------------------------------------------------


class TestTerminalOutcome:
    def test_terminal_outcome_success(self, writer, mock_state_manager):
        writer.record_terminal_outcome("answered", "LOCAL", execution_time_ms=50)
        assert mock_state_manager.write_outcome.called
        args, _ = mock_state_manager.write_outcome.call_args
        assert args[0]["success"] is True
        assert args[0]["duration_ms"] == 50
        assert args[0]["result"]["outcome_code"] == "answered"
        assert args[0]["result"]["mode"] == "LOCAL"

    def test_terminal_outcome_error(self, writer, mock_state_manager):
        writer.record_terminal_outcome("execution_error", "LOCAL", error_msg="boom", execution_time_ms=10)
        args, _ = mock_state_manager.write_outcome.call_args
        assert args[0]["success"] is False
        assert args[0]["error_message"] == "boom"

    def test_terminal_outcome_sqlite_disabled(self, mock_state_manager, mock_logger):
        writer = StateWriter(
            state_dir=Path("/tmp"),
            state_manager=mock_state_manager,
            logger=mock_logger,
            use_sqlite_state=False,
        )
        writer.record_terminal_outcome("answered", "LOCAL")
        assert not mock_state_manager.write_outcome.called

    def test_terminal_outcome_sqlite_failure_logged(self, writer, mock_state_manager, caplog):
        mock_state_manager.write_outcome.side_effect = RuntimeError("db locked")
        with caplog.at_level(logging.ERROR, logger="test_state_writer"):
            writer.record_terminal_outcome("answered", "LOCAL")
        assert "db locked" in caplog.text


# ---------------------------------------------------------------------------
# Close / cleanup
# ---------------------------------------------------------------------------


class TestClose:
    def test_close_delegates(self, writer, mock_state_manager):
        writer.close()
        assert mock_state_manager.close.called

    def test_close_failure_logged(self, writer, mock_state_manager, caplog):
        mock_state_manager.close.side_effect = RuntimeError("already closed")
        with caplog.at_level(logging.WARNING, logger="test_state_writer"):
            writer.close()
        assert "already closed" in caplog.text


# ---------------------------------------------------------------------------
# File locking behavior
# ---------------------------------------------------------------------------


class TestFileLocking:
    def test_lock_yields(self, writer, tmp_state_dir):
        target = tmp_state_dir / "lock_test.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        # Should not raise
        with writer._file_lock(target):
            pass

    def test_lock_retry_on_contention(self, writer, tmp_state_dir):
        route_file = tmp_state_dir / "contention.json"
        route_file.parent.mkdir(parents=True, exist_ok=True)
        # Hold an external lock
        import fcntl
        lock_path = Path(str(route_file) + ".lock")
        with open(lock_path, "w") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            # StateWriter lock should time out gracefully and proceed best-effort
            # We use a very short backoff to keep the test fast
            with writer._file_lock(route_file, max_retries=1, backoff_base_ms=1.0):
                pass
            fcntl.flock(lf, fcntl.LOCK_UN)


class TestPIIRedaction:
    """Test PII redaction in StateWriter."""

    def test_redact_email_in_json_payload(self, writer, sample_route, sample_result, tmp_path, monkeypatch):
        """PII in question must be redacted in JSON payload request_text."""
        monkeypatch.setenv("LUCY_UI_STATE_DIR", str(tmp_path))
        ctx = {
            "question": "Contact me at john.doe@example.com please",
            "intent": "local_answer",
            "is_medical_query": False,
        }
        writer.write_json_state_files(sample_route, sample_result, ctx)
        payload = json.loads((tmp_path / "last_request_result.json").read_text(encoding="utf-8"))
        assert "[REDACTED-EMAIL]" in payload["request_text"]
        assert "john.doe@example.com" not in payload["request_text"]

    def test_redact_phone_in_json_payload(self, writer, sample_route, sample_result, tmp_path, monkeypatch):
        """PII in question must be redacted in JSON payload request_text."""
        monkeypatch.setenv("LUCY_UI_STATE_DIR", str(tmp_path))
        ctx = {"question": "My number is 555-123-4567", "intent": "local_answer"}
        writer.write_json_state_files(sample_route, sample_result, ctx)
        payload = json.loads((tmp_path / "last_request_result.json").read_text(encoding="utf-8"))
        assert "[REDACTED-PHONE]" in payload["request_text"]
        assert "555-123-4567" not in payload["request_text"]

    def test_redact_ssn_in_json_payload(self, writer, sample_route, sample_result, tmp_path, monkeypatch):
        """PII in question must be redacted in JSON payload request_text."""
        monkeypatch.setenv("LUCY_UI_STATE_DIR", str(tmp_path))
        ctx = {"question": "SSN is 123-45-6789", "intent": "local_answer"}
        writer.write_json_state_files(sample_route, sample_result, ctx)
        payload = json.loads((tmp_path / "last_request_result.json").read_text(encoding="utf-8"))
        assert "[REDACTED-SSN]" in payload["request_text"]
        assert "123-45-6789" not in payload["request_text"]

    def test_no_redaction_for_clean_text_in_json(self, writer, sample_route, sample_result, tmp_path, monkeypatch):
        """Clean text must pass through unchanged in JSON payload."""
        monkeypatch.setenv("LUCY_UI_STATE_DIR", str(tmp_path))
        ctx = {"question": "What is the capital of France?", "intent": "local_answer"}
        writer.write_json_state_files(sample_route, sample_result, ctx)
        payload = json.loads((tmp_path / "last_request_result.json").read_text(encoding="utf-8"))
        assert "What is the capital of France?" in payload["request_text"]
        assert "REDACTED" not in payload["request_text"]

    def test_redact_error_message_in_sqlite(self, writer, mock_state_manager):
        """PII in error_message must be redacted before SQLite write."""
        route = RoutingDecision(
            route="LOCAL", mode="AUTO", intent_family="local_answer",
            confidence=0.90, provider="local", provider_usage_class="local",
            evidence_mode="",
        )
        result = ExecutionResult(
            status="failed", outcome_code="execution_error",
            route="LOCAL", provider="local", provider_usage_class="local",
            response_text="", error_message="Failed for user@corp.org",
            execution_time_ms=5000, metadata={},
        )
        writer.write_state(route, result, {"question": "What?"})
        outcome_call = mock_state_manager.write_outcome.call_args
        assert "[REDACTED-EMAIL]" in outcome_call[0][0]["error_message"]


# ---------------------------------------------------------------------------
# HMI-facing JSON state files
# ---------------------------------------------------------------------------


class TestJsonStateFiles:
    """Test StateWriter JSON state file publishing (Option A)."""

    def test_write_json_creates_result_file(self, writer, sample_route, sample_result, sample_context, tmp_path, monkeypatch):
        monkeypatch.setenv("LUCY_UI_STATE_DIR", str(tmp_path))
        writer.write_json_state_files(sample_route, sample_result, sample_context)
        assert (tmp_path / "last_request_result.json").exists()

    def test_write_json_creates_route_file(self, writer, sample_route, sample_result, sample_context, tmp_path, monkeypatch):
        monkeypatch.setenv("LUCY_UI_STATE_DIR", str(tmp_path))
        writer.write_json_state_files(sample_route, sample_result, sample_context)
        assert (tmp_path / "last_route.json").exists()

    def test_write_json_creates_history_file(self, writer, sample_route, sample_result, sample_context, tmp_path, monkeypatch):
        monkeypatch.setenv("LUCY_UI_STATE_DIR", str(tmp_path))
        writer.write_json_state_files(sample_route, sample_result, sample_context)
        assert (tmp_path / "request_history.jsonl").exists()

    def test_result_payload_schema(self, writer, sample_route, sample_result, sample_context, tmp_path, monkeypatch):
        monkeypatch.setenv("LUCY_UI_STATE_DIR", str(tmp_path))
        writer.write_json_state_files(sample_route, sample_result, sample_context)
        payload = json.loads((tmp_path / "last_request_result.json").read_text(encoding="utf-8"))
        assert payload["status"] == "completed"
        assert payload["request_text"] == "What is the meaning of life?"
        assert payload["response_text"] == "The answer is 42."
        assert payload["route"]["mode"] == "LOCAL"
        assert payload["outcome"]["outcome_code"] == "answered"
        assert payload["outcome"]["trust_class"] == "local"
        assert payload["outcome"]["augmented_provider_used"] == "none"
        assert payload["control_state"]["mode"] == "auto"
        assert payload["control_state"]["memory"] == "off"
        assert "request_id" in payload
        assert payload["error"] == ""

    def test_route_snapshot_schema(self, writer, sample_route, sample_result, sample_context, tmp_path, monkeypatch):
        monkeypatch.setenv("LUCY_UI_STATE_DIR", str(tmp_path))
        writer.write_json_state_files(sample_route, sample_result, sample_context)
        snapshot = json.loads((tmp_path / "last_route.json").read_text(encoding="utf-8"))
        assert snapshot["current_route"] == "LOCAL"
        assert snapshot["route"] == "LOCAL"
        assert snapshot["source_type"] == "local"
        assert snapshot["source"] == "local"
        assert snapshot["trust_class"] == "local"
        assert snapshot["outcome_code"] == "answered"
        assert snapshot["provider_used"] == "none"
        assert "authority" in snapshot

    def test_history_entry_schema(self, writer, sample_route, sample_result, sample_context, tmp_path, monkeypatch):
        monkeypatch.setenv("LUCY_UI_STATE_DIR", str(tmp_path))
        writer.write_json_state_files(sample_route, sample_result, sample_context)
        lines = (tmp_path / "request_history.jsonl").read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["status"] == "completed"
        assert entry["request_text"] == "What is the meaning of life?"
        assert entry["route"]["mode"] == "LOCAL"
        assert entry["outcome"]["outcome_code"] == "answered"
        assert "request_id" in entry

    def test_history_deduplication(self, writer, sample_route, sample_result, sample_context, tmp_path, monkeypatch):
        monkeypatch.setenv("LUCY_UI_STATE_DIR", str(tmp_path))
        # First write
        writer.write_json_state_files(sample_route, sample_result, sample_context)
        # Second write with same request_id
        writer.write_json_state_files(sample_route, sample_result, sample_context)
        lines = (tmp_path / "request_history.jsonl").read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1

    def test_augmented_route_provider(self, writer, sample_context, tmp_path, monkeypatch):
        monkeypatch.setenv("LUCY_UI_STATE_DIR", str(tmp_path))
        route = RoutingDecision(
            route="AUGMENTED", mode="AUTO", intent_family="factual",
            confidence=0.88, provider="openai", provider_usage_class="paid",
            evidence_mode="",
        )
        result = ExecutionResult(
            status="completed", outcome_code="augmented_answer",
            route="AUGMENTED", provider="openai", provider_usage_class="paid",
            response_text="Answer.", execution_time_ms=200,
            metadata={"trust_class": "unverified", "augmented_direct_request": "1"},
        )
        writer.write_json_state_files(route, result, sample_context)
        payload = json.loads((tmp_path / "last_request_result.json").read_text(encoding="utf-8"))
        assert payload["route"]["mode"] == "AUGMENTED"
        assert payload["outcome"]["augmented_provider_used"] == "openai"
        assert payload["outcome"]["augmented_paid_provider_invoked"] == "true"
        snapshot = json.loads((tmp_path / "last_route.json").read_text(encoding="utf-8"))
        assert snapshot["current_route"] == "AUGMENTED"
        assert snapshot["source_type"] == "openai"

    def test_wikipedia_route_paid_false(self, writer, sample_context, tmp_path, monkeypatch):
        monkeypatch.setenv("LUCY_UI_STATE_DIR", str(tmp_path))
        route = RoutingDecision(
            route="AUGMENTED", mode="AUTO", intent_family="factual",
            confidence=0.85, provider="wikipedia", provider_usage_class="free",
            evidence_mode="",
        )
        result = ExecutionResult(
            status="completed", outcome_code="augmented_answer",
            route="AUGMENTED", provider="wikipedia", provider_usage_class="free",
            response_text="Answer.", execution_time_ms=150,
            metadata={"trust_class": "evidence_backed"},
        )
        writer.write_json_state_files(route, result, sample_context)
        payload = json.loads((tmp_path / "last_request_result.json").read_text(encoding="utf-8"))
        assert payload["outcome"]["augmented_provider_used"] == "wikipedia"
        assert payload["outcome"]["augmented_paid_provider_invoked"] == "false"

    def test_error_case(self, writer, sample_context, tmp_path, monkeypatch):
        monkeypatch.setenv("LUCY_UI_STATE_DIR", str(tmp_path))
        route = RoutingDecision(
            route="LOCAL", mode="AUTO", intent_family="local_answer",
            confidence=0.90, provider="local", provider_usage_class="local",
            evidence_mode="",
        )
        result = ExecutionResult(
            status="failed", outcome_code="execution_error",
            route="LOCAL", provider="local", provider_usage_class="local",
            response_text="", error_message="Model timeout",
            execution_time_ms=5000, metadata={},
        )
        writer.write_json_state_files(route, result, sample_context)
        payload = json.loads((tmp_path / "last_request_result.json").read_text(encoding="utf-8"))
        assert payload["status"] == "failed"
        assert payload["error"] == "Model timeout"
        snapshot = json.loads((tmp_path / "last_route.json").read_text(encoding="utf-8"))
        assert snapshot["status"] == "failed"
        assert snapshot["outcome_code"] == "execution_error"

    def test_control_state_from_env(self, writer, sample_route, sample_result, tmp_path, monkeypatch):
        monkeypatch.setenv("LUCY_UI_STATE_DIR", str(tmp_path))
        monkeypatch.setenv("LUCY_SESSION_MEMORY", "1")
        monkeypatch.setenv("LUCY_EVIDENCE_ENABLED", "1")
        monkeypatch.setenv("LUCY_VOICE_ENABLED", "1")
        monkeypatch.setenv("LUCY_MODEL", "local-lucy-qwen3")
        monkeypatch.setenv("LUCY_AUGMENTATION_POLICY", "fallback_only")
        monkeypatch.setenv("LUCY_AUGMENTED_PROVIDER", "openai")
        writer.write_json_state_files(sample_route, sample_result, {"question": "Hello"})
        payload = json.loads((tmp_path / "last_request_result.json").read_text(encoding="utf-8"))
        cs = payload["control_state"]
        assert cs["memory"] == "on"
        assert cs["evidence"] == "on"
        assert cs["voice"] == "on"
        assert cs["model"] == "local-lucy-qwen3"
        assert cs["augmentation_policy"] == "fallback_only"
        assert cs["augmented_provider"] == "openai"

    def test_no_exception_on_failure(self, writer, sample_route, sample_result, sample_context, tmp_path, monkeypatch, caplog):
        """JSON write failures must be swallowed (same contract as .env writes)."""
        monkeypatch.setenv("LUCY_UI_STATE_DIR", str(tmp_path))
        # Make the directory a file to force a write error
        (tmp_path / "last_request_result.json").mkdir(parents=True, exist_ok=True)
        # This should NOT raise
        with caplog.at_level(logging.WARNING, logger="test_state_writer"):
            writer.write_json_state_files(sample_route, sample_result, sample_context)
        assert "Failed to write JSON state files" in caplog.text

    def test_request_id_propagation(self, writer, sample_route, sample_result, tmp_path, monkeypatch):
        """request_id from main.py must flow through context into JSON payload and SQLite."""
        monkeypatch.setenv("LUCY_UI_STATE_DIR", str(tmp_path))
        ctx = {
            "question": "What is the meaning of life?",
            "resolved_question": "What is the meaning of life?",
            "intent": "local_answer",
            "is_medical_query": False,
            "request_id": "a3f7b2d9e8c1d4e5",
        }
        writer.write_json_state_files(sample_route, sample_result, ctx)
        payload = json.loads((tmp_path / "last_request_result.json").read_text(encoding="utf-8"))
        assert payload["request_id"] == "a3f7b2d9e8c1d4e5"
        # Also verify SQLite metadata carries request_id
        mock_sm = MagicMock()
        writer_sqlite = StateWriter("default", state_manager=mock_sm, logger=logging.getLogger("test"))
        writer_sqlite._write_state_to_sqlite(sample_route, sample_result, ctx)
        route_call = mock_sm.write_route.call_args[0][0]
        assert route_call["metadata"]["request_id"] == "a3f7b2d9e8c1d4e5"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
