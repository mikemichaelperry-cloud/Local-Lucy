#!/usr/bin/env python3
"""Tests for the cross-model memory continuity step in stage 13."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent

sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "ui-v10"))
sys.path.insert(0, str(ROOT))

import tools.router_py.stage_13_model_switch as stage_13


@pytest.fixture(autouse=True)
def _isolate_env():
    """Preserve environment variables touched by the memory step."""
    preserve = {"LUCY_SESSION_MEMORY", "LUCY_SESSION_ID"}
    original = {k: os.environ.get(k) for k in preserve}
    yield
    for k, v in original.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _make_step_result(response_text: str, passed: bool = True) -> dict:
    return {
        "model": "mock-model",
        "question": "mock-question",
        "route": "LOCAL",
        "status": "completed" if passed else "failed",
        "outcome_code": "answered",
        "response_text": response_text,
        "response_len": len(response_text),
        "loaded_models": ["mock-model"],
        "elapsed_s": 0.1,
        "passed": passed,
        "notes": [],
    }


def test_memory_continuation_passes_when_llama_references_oscar():
    def fake_run_step(model: str, question: str) -> dict:
        if "Oscar" in question:
            return _make_step_result("Oscar found a hidden key under the old oak tree.")
        return _make_step_result("Oscar then unlocked the garden gate and stepped inside.")

    with (
        patch.object(stage_13, "_load_model_exclusively"),
        patch.object(stage_13, "_set_state_model"),
        patch.object(stage_13, "_run_step", side_effect=fake_run_step),
    ):
        result = stage_13._run_memory_continuation_step()

    assert result["passed"] is True
    assert result["mentions_oscar"] is True
    assert result["continues_narrative"] is True
    assert result["notes"] == []


def test_memory_continuation_fails_when_oscar_missing():
    def fake_run_step(model: str, question: str) -> dict:
        if "Oscar" in question:
            return _make_step_result("Oscar found a hidden key under the old oak tree.")
        return _make_step_result("The robot walked through the field and saw nothing special.")

    with (
        patch.object(stage_13, "_load_model_exclusively"),
        patch.object(stage_13, "_set_state_model"),
        patch.object(stage_13, "_run_step", side_effect=fake_run_step),
    ):
        result = stage_13._run_memory_continuation_step()

    assert result["passed"] is False
    assert result["mentions_oscar"] is False
    assert "continuation does not reference Oscar" in result["notes"]


def test_memory_continuation_fails_when_narrative_does_not_advance():
    def fake_run_step(model: str, question: str) -> dict:
        if "Oscar" in question:
            return _make_step_result("Oscar found a hidden key under the old oak tree.")
        return _make_step_result("Oscar.")

    with (
        patch.object(stage_13, "_load_model_exclusively"),
        patch.object(stage_13, "_set_state_model"),
        patch.object(stage_13, "_run_step", side_effect=fake_run_step),
    ):
        result = stage_13._run_memory_continuation_step()

    assert result["passed"] is False
    assert result["mentions_oscar"] is True
    assert result["continues_narrative"] is False
    assert "continuation does not appear to advance the narrative" in result["notes"]


def test_memory_continuation_fails_when_gemma_step_fails():
    def fake_run_step(model: str, question: str) -> dict:
        if "Oscar" in question:
            return _make_step_result("error", passed=False)
        return _make_step_result("Oscar then unlocked the garden gate.")

    with (
        patch.object(stage_13, "_load_model_exclusively"),
        patch.object(stage_13, "_set_state_model"),
        patch.object(stage_13, "_run_step", side_effect=fake_run_step),
    ):
        result = stage_13._run_memory_continuation_step()

    assert result["passed"] is False


def test_memory_continuation_fails_when_llama_step_fails():
    def fake_run_step(model: str, question: str) -> dict:
        if "Oscar" in question:
            return _make_step_result("Oscar found a hidden key.")
        return _make_step_result("error", passed=False)

    with (
        patch.object(stage_13, "_load_model_exclusively"),
        patch.object(stage_13, "_set_state_model"),
        patch.object(stage_13, "_run_step", side_effect=fake_run_step),
    ):
        result = stage_13._run_memory_continuation_step()

    assert result["passed"] is False


def test_memory_continuation_uses_fixed_session_id():
    captured = {}

    def fake_run_step(model: str, question: str) -> dict:
        captured["session_memory"] = os.environ.get("LUCY_SESSION_MEMORY")
        captured["session_id"] = os.environ.get("LUCY_SESSION_ID")
        return _make_step_result("Oscar continued the adventure.")

    with (
        patch.object(stage_13, "_load_model_exclusively"),
        patch.object(stage_13, "_set_state_model"),
        patch.object(stage_13, "_run_step", side_effect=fake_run_step),
    ):
        stage_13._run_memory_continuation_step()

    assert captured["session_memory"] == "1"
    assert captured["session_id"] == stage_13.MEMORY_SESSION_ID


def test_memory_continuation_restores_env_vars():
    os.environ["LUCY_SESSION_MEMORY"] = "0"
    os.environ["LUCY_SESSION_ID"] = "prior-session"

    with (
        patch.object(stage_13, "_load_model_exclusively"),
        patch.object(stage_13, "_set_state_model"),
        patch.object(
            stage_13, "_run_step", side_effect=lambda _m, _q: _make_step_result("Oscar continued.")
        ),
    ):
        stage_13._run_memory_continuation_step()

    assert os.environ.get("LUCY_SESSION_MEMORY") == "0"
    assert os.environ.get("LUCY_SESSION_ID") == "prior-session"


def test_run_step_includes_response_text():
    """The step dict must expose response_text for downstream verification."""
    outcome = SimpleNamespace(
        status="completed",
        route="LOCAL",
        outcome_code="answered",
        response_text="Paris is the capital of France.",
    )

    with (
        patch.object(stage_13, "_lucy_models_loaded", return_value=["local-lucy-gemma4:latest"]),
        patch.object(stage_13, "execute_plan_python", return_value=outcome),
    ):
        result = stage_13._run_step("local-lucy-gemma4:latest", "What is the capital of France?")

    assert result["response_text"] == "Paris is the capital of France."
    assert result["passed"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
