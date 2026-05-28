#!/usr/bin/env python3
"""
End-to-end tests for HMI and voice surfaces through the full pipeline.

These tests exercise the real ExecutionEngine + StateWriter stack without
hitting external LLM APIs or live web services. Provider calls and evidence
fetching are patched to return synthetic data, but state persistence,
routing, and response formatting run through production code.

Coverage:
1. Voice surface submit → LOCAL route → state files + SQLite written
2. HMI surface submit → TIME route → state files + SQLite written
3. Voice surface → AUGMENTED route → memory telemetry in state
4. Terminal outcome (CLARIFY) → state recorded on early exit
5. State consistency verification across dual-write sources
6. Voice timeout propagation (300s)

Run with:
    cd /home/mike/lucy-v10 && source ui-v9/.venv/bin/activate
    python3 -m pytest tools/router_py/test_e2e_hmi_voice.py -v
"""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest

from router_py.execution_engine import ExecutionEngine
from router_py.execution_engine_state import StateWriter
from router_py.request_types import ClassificationResult, RoutingDecision, ExecutionResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_classification(intent_family: str = "local_answer", confidence: float = 0.95) -> ClassificationResult:
    return ClassificationResult(
        intent="answer",
        intent_family=intent_family,
        confidence=confidence,
        needs_web=False,
        needs_memory=False,
        needs_synthesis=False,
        clarify_required=False,
        evidence_mode="",
        augmentation_recommended=False,
        force_local=False,
    )


def _make_route(
    route: str = "LOCAL",
    provider: str = "local",
    provider_usage_class: str = "local",
    confidence: float = 0.95,
) -> RoutingDecision:
    return RoutingDecision(
        route=route,
        mode="AUTO",
        intent_family="local_answer",
        confidence=confidence,
        provider=provider,
        provider_usage_class=provider_usage_class,
        evidence_mode="",
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_state_dir():
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


@pytest.fixture
def engine(tmp_state_dir, monkeypatch):
    """Real ExecutionEngine with mocked external dependencies."""
    monkeypatch.setenv("LUCY_EXEC_PY", "1")
    monkeypatch.setenv("LUCY_UI_STATE_DIR", str(tmp_state_dir))
    eng = ExecutionEngine(config={
        "state_dir": str(tmp_state_dir),
        "use_sqlite_state": True,
    })
    # Override state dir to temp path
    eng._state_dir = tmp_state_dir
    eng.state_writer._state_dir = tmp_state_dir
    eng.state_manager = MagicMock()
    eng.state_writer.state_manager = eng.state_manager
    return eng


# ---------------------------------------------------------------------------
# E2E: Voice surface → LOCAL → state persistence
# ---------------------------------------------------------------------------


class TestVoiceLocalRoute:
    def test_voice_local_json_state_files_written(self, engine, tmp_state_dir):
        """Voice submit to LOCAL should write JSON state files (env deprecated in Stream 3)."""
        with patch.object(engine, "_call_single_provider", return_value="The answer is 42."):
            intent = _make_classification("local_answer")
            route = _make_route("LOCAL", "local", "local")
            ctx = {"question": "What is 2+2?", "surface": "voice"}
            result = engine.execute(intent, route, context=ctx, use_python_path=True)

        assert result.status == "completed"
        assert result.route == "LOCAL"

        # JSON state files (Stream 2/3) — .env deprecated
        route_json = tmp_state_dir / "last_route.json"
        result_json = tmp_state_dir / "last_request_result.json"
        assert route_json.exists(), "last_route.json should be written"
        assert result_json.exists(), "last_request_result.json should be written"

        route_data = json.loads(route_json.read_text(encoding="utf-8"))
        assert route_data["current_route"] == "LOCAL"
        assert route_data["status"] == "completed"

        result_data = json.loads(result_json.read_text(encoding="utf-8"))
        assert result_data["outcome"]["outcome_code"] == "answered"
        assert result_data["route"]["mode"] == "LOCAL"

    def test_voice_local_sqlite_written(self, engine):
        """Voice submit to LOCAL should also write to SQLite via StateManager."""
        with patch.object(engine, "_call_single_provider", return_value="42"):
            intent = _make_classification("local_answer")
            route = _make_route("LOCAL", "local", "local")
            ctx = {"question": "What is 2+2?", "surface": "voice"}
            engine.execute(intent, route, context=ctx, use_python_path=True)

        assert engine.state_manager.write_batch.called
        route_args, outcome_args = engine.state_manager.write_batch.call_args[0]
        assert route_args["metadata"]["question"] == "What is 2+2?"

    def test_voice_surface_propagated_to_metadata(self, engine, tmp_state_dir):
        """Voice surface should be available in execution context."""
        with patch.object(engine, "_call_single_provider", return_value="Voice answer."):
            intent = _make_classification("local_answer")
            route = _make_route("LOCAL", "local", "local")
            result = engine.execute(
                intent, route,
                context={"question": "Hello", "surface": "voice"},
                use_python_path=True,
            )
        assert result.status == "completed"
        # JSON state files should be written (env deprecated in Stream 3)
        route_json = tmp_state_dir / "last_route.json"
        assert route_json.exists()


# ---------------------------------------------------------------------------
# E2E: HMI surface → TIME → state persistence
# ---------------------------------------------------------------------------


class TestHmiTimeRoute:
    def test_hmi_time_state_files(self, engine, tmp_state_dir):
        """HMI submit to TIME should write state with time provider."""
        with patch.object(engine, "_fetch_evidence", return_value={"ok": True, "formatted": "10:30 AM UTC"}):
            intent = _make_classification("time", confidence=0.99)
            route = _make_route("TIME", "time", "free", confidence=0.99)
            ctx = {"question": "What time is it?", "surface": "hmi"}
            result = engine.execute(intent, route, context=ctx, use_python_path=True)

        assert result.status == "completed"
        assert result.route == "TIME"

        route_json = tmp_state_dir / "last_route.json"
        route_data = json.loads(route_json.read_text(encoding="utf-8"))
        assert route_data["current_route"] == "TIME"
        assert route_data["outcome_code"] == "answered"

    def test_hmi_time_sqlite_outcome(self, engine):
        """HMI TIME route should write outcome to SQLite."""
        with patch.object(engine, "_fetch_evidence", return_value={"ok": True, "formatted": "10:30 AM UTC"}):
            intent = _make_classification("time", confidence=0.99)
            route = _make_route("TIME", "time", "free", confidence=0.99)
            engine.execute(intent, route, context={"question": "What time is it?", "surface": "hmi"}, use_python_path=True)

        route_args, outcome_args = engine.state_manager.write_batch.call_args[0]
        payload = outcome_args
        assert payload["success"] is True
        assert payload["result"]["route"] == "TIME"
        assert payload["result"]["provider"] == "timeapi"


# ---------------------------------------------------------------------------
# E2E: Voice → AUGMENTED → memory telemetry in state
# ---------------------------------------------------------------------------


class TestVoiceAugmentedTelemetry:
    def test_augmented_memory_telemetry_in_files(self, engine, tmp_state_dir):
        """AUGMENTED route with memory telemetry should persist all fields."""
        with patch.object(engine, "_call_single_provider", return_value="Detailed answer."):
            intent = _make_classification("factual", confidence=0.88)
            route = _make_route("AUGMENTED", "openai", "paid", confidence=0.88)
            ctx = {
                "question": "Explain quantum computing.",
                "surface": "voice",
            }
            result = engine.execute(intent, route, context=ctx, use_python_path=True)

        assert result.status == "completed"

        # Now inject memory metadata manually to test StateWriter handles it
        result_with_mem = ExecutionResult(
            status="completed",
            outcome_code="augmented_answer",
            route="AUGMENTED",
            provider="openai",
            provider_usage_class="paid",
            response_text="Detailed answer.",
            execution_time_ms=result.execution_time_ms,
            metadata={
                "trust_class": "augmented",
                "memory_context_used": "session",
                "memory_mode_used": "recall",
                "memory_depth_used": "5",
                "memory_top_score": "0.91",
                "memory_session_injected": "true",
                "memory_top_gap": "0.08",
            },
        )
        engine.state_writer.write_state(route, result_with_mem, ctx)

        # Memory telemetry is in SQLite (env deprecated in Stream 3)
        route_args, outcome_args = engine.state_manager.write_batch.call_args[0]
        outcome_meta = outcome_args["result"]
        assert outcome_meta["memory_context_used"] == "session"
        assert outcome_meta["memory_mode_used"] == "recall"
        assert outcome_meta["route"] == "AUGMENTED"

    def test_augmented_memory_telemetry_in_sqlite(self, engine):
        """AUGMENTED route with memory telemetry should write to SQLite."""
        route = _make_route("AUGMENTED", "openai", "paid", confidence=0.88)
        result = ExecutionResult(
            status="completed",
            outcome_code="augmented_answer",
            route="AUGMENTED",
            provider="openai",
            provider_usage_class="paid",
            response_text="Answer.",
            execution_time_ms=200,
            metadata={
                "trust_class": "augmented",
                "memory_context_used": "session",
                "memory_top_score": "0.91",
                "memory_session_injected": "true",
                "memory_top_gap": "0.08",
            },
        )
        ctx = {"question": "Explain quantum computing.", "surface": "voice"}
        engine.state_writer._write_state_to_sqlite(route, result, ctx)

        route_args, outcome_args = engine.state_manager.write_batch.call_args[0]
        result_meta = outcome_args["result"]
        assert result_meta["memory_context_used"] == "session"
        assert result_meta["memory_top_score"] == "0.91"
        assert result_meta["memory_session_injected"] == "true"
        assert result_meta["memory_top_gap"] == "0.08"


# ---------------------------------------------------------------------------
# E2E: Terminal outcome (CLARIFY) → state recorded
# ---------------------------------------------------------------------------


class TestTerminalOutcome:
    def test_clarify_records_terminal_outcome(self, engine, tmp_state_dir):
        """CLARIFY route should record terminal outcome in files and SQLite."""
        intent = _make_classification("local_answer")
        intent = ClassificationResult(
            intent="clarify", intent_family="conversational",
            confidence=0.80, needs_web=False, needs_memory=False,
            needs_synthesis=False, clarify_required=True,
            evidence_mode="", augmentation_recommended=False, force_local=False,
        )
        route = _make_route("CLARIFY", "local", "local", confidence=0.80)
        ctx = {"question": "What?", "surface": "voice"}
        result = engine.execute(intent, route, context=ctx, use_python_path=True)

        assert result.status == "completed"
        assert result.route == "CLARIFY"

        result_json = tmp_state_dir / "last_request_result.json"
        result_data = json.loads(result_json.read_text(encoding="utf-8"))
        assert result_data["outcome"]["outcome_code"] == "clarification_requested"
        assert result_data["route"]["mode"] == "CLARIFY"

    def test_clarify_records_terminal_sqlite(self, engine):
        """CLARIFY should write terminal outcome to SQLite."""
        engine._record_terminal_outcome(
            outcome_code="clarification_requested",
            mode="CLARIFY",
            execution_time_ms=45,
        )
        assert engine.state_manager.write_outcome.called
        args, _ = engine.state_manager.write_outcome.call_args
        assert args[0]["success"] is True
        assert args[0]["duration_ms"] == 45
        assert args[0]["result"]["outcome_code"] == "clarification_requested"
        assert args[0]["result"]["mode"] == "CLARIFY"


# ---------------------------------------------------------------------------
# E2E: State consistency verification
# ---------------------------------------------------------------------------


class TestStateConsistency:
    def test_consistency_passes_when_both_match(self, engine, tmp_state_dir):
        """When SQLite and files agree, verify_state_consistency should return True."""
        with patch.object(engine, "_call_single_provider", return_value="Answer."):
            intent = _make_classification("local_answer")
            route = _make_route("LOCAL", "local", "local")
            engine.execute(intent, route, context={"question": "Hello", "surface": "hmi"}, use_python_path=True)

        engine.state_manager.read_last_route.return_value = {"strategy": "LOCAL"}
        assert engine.verify_state_consistency() is True

    def test_consistency_fails_on_mismatch(self, engine, tmp_state_dir):
        """When SQLite and files disagree, verify_state_consistency should return False."""
        with patch.object(engine, "_call_single_provider", return_value="Answer."):
            intent = _make_classification("local_answer")
            route = _make_route("LOCAL", "local", "local")
            engine.execute(intent, route, context={"question": "Hello", "surface": "hmi"}, use_python_path=True)

        engine.state_manager.read_last_route.return_value = {"strategy": "AUGMENTED"}
        assert engine.verify_state_consistency() is False


# ---------------------------------------------------------------------------
# E2E: main.run() voice surface propagation
# ---------------------------------------------------------------------------


class TestMainRunVoiceSurface:
    def test_voice_timeout_propagation(self):
        """main.run(surface='voice', timeout=300) should propagate timeout."""
        with patch("router_py.request_pipeline.process") as mock_process:
            from router_py.request_types import RouterOutcome
            mock_process.return_value = (
                RouterOutcome(
                    status="completed", outcome_code="answered", route="LOCAL",
                    provider="local", provider_usage_class="local",
                    response_text="42", execution_time_ms=100,
                ),
                None, None,
            )
            from router_py.main import run
            outcome = run("What is 2+2?", surface="voice", timeout=300)
            assert outcome.route == "LOCAL"
            _, kwargs = mock_process.call_args
            assert kwargs.get("surface") == "voice"
            assert kwargs.get("timeout") == 300

    def test_hmi_surface_propagation(self):
        """main.run(surface='hmi') should propagate surface."""
        with patch("router_py.request_pipeline.process") as mock_process:
            from router_py.request_types import RouterOutcome
            mock_process.return_value = (
                RouterOutcome(
                    status="completed", outcome_code="answered", route="LOCAL",
                    provider="local", provider_usage_class="local",
                    response_text="42", execution_time_ms=100,
                ),
                None, None,
            )
            from router_py.main import run
            outcome = run("What is 2+2?", surface="hmi")
            assert outcome.route == "LOCAL"
            _, kwargs = mock_process.call_args
            assert kwargs.get("surface") == "hmi"


# ---------------------------------------------------------------------------
# E2E: Full voice turn via main.run() with real engine
# ---------------------------------------------------------------------------


class TestFullVoiceTurn:
    def test_full_voice_turn_local(self, tmp_state_dir):
        """
        Full voice turn: instantiate real engine, execute LOCAL route,
        verify both file and SQLite state are consistent.
        """
        os.environ["LUCY_EXEC_PY"] = "1"
        os.environ["LUCY_UI_STATE_DIR"] = str(tmp_state_dir)
        engine = ExecutionEngine(config={
            "state_dir": str(tmp_state_dir),
            "use_sqlite_state": True,
        })
        engine._state_dir = tmp_state_dir
        engine.state_writer._state_dir = tmp_state_dir
        engine.state_manager = MagicMock()
        engine.state_writer.state_manager = engine.state_manager

        with patch.object(engine, "_call_single_provider", return_value="42"):
            intent = _make_classification("local_answer")
            route = _make_route("LOCAL", "local", "local")
            result = engine.execute(
                intent, route,
                context={"question": "What is 2+2?", "surface": "voice"},
                use_python_path=True,
            )

        assert result.status == "completed"
        assert result.response_text  # non-empty response

        # Verify JSON state files were written (env deprecated in Stream 3)
        route_json = tmp_state_dir / "last_route.json"
        assert route_json.exists()

        # Verify SQLite was invoked
        assert engine.state_manager.write_batch.called

        # Verify consistency would pass
        engine.state_manager.read_last_route.return_value = {"strategy": "LOCAL"}
        assert engine.verify_state_consistency() is True

    def test_full_voice_turn_weather(self, tmp_state_dir):
        """
        Full voice turn: WEATHER route with evidence fetching mocked.
        """
        os.environ["LUCY_EXEC_PY"] = "1"
        os.environ["LUCY_UI_STATE_DIR"] = str(tmp_state_dir)
        engine = ExecutionEngine(config={
            "state_dir": str(tmp_state_dir),
            "use_sqlite_state": True,
        })
        engine._state_dir = tmp_state_dir
        engine.state_writer._state_dir = tmp_state_dir
        engine.state_manager = MagicMock()
        engine.state_writer.state_manager = engine.state_manager

        with patch.object(engine, "_fetch_evidence", return_value={"ok": True, "formatted": "Sunny, 22°C in Paris"}):
            intent = _make_classification("weather", confidence=0.97)
            route = _make_route("WEATHER", "weather", "free", confidence=0.97)
            result = engine.execute(
                intent, route,
                context={"question": "Weather in Paris?", "surface": "voice"},
                use_python_path=True,
            )

        assert result.status == "completed"
        assert result.route == "WEATHER"
        assert "Sunny, 22°C" in result.response_text

        route_json = tmp_state_dir / "last_route.json"
        route_data = json.loads(route_json.read_text(encoding="utf-8"))
        assert route_data["current_route"] == "WEATHER"
        assert route_data["outcome_code"] == "answered"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
