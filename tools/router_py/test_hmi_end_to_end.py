"""Static HMI surface injection-to-output tests.

These tests instantiate `RuntimeBridge` with a disposable namespace and state
file, mock the backend `runtime_request.submit_request` call so no Ollama or
network access is required, and assert on the returned `CommandResult.payload`.

Run with the system Python (no UI venv required):

    cd /home/mike/lucy-v11
    python3 -m pytest tools/router_py/test_hmi_end_to_end.py -v
"""

from __future__ import annotations

import json
import os
import sys
import types
from pathlib import Path
from typing import Any

import pytest

# Make `router_py` importable for `RuntimeBridge` and for the bridge's own
# direct `router_py.main` / `router_py.model_selector` imports.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_ROUTER_PY_ROOT = _PROJECT_ROOT / "tools" / "router_py"
if str(_ROUTER_PY_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROUTER_PY_ROOT))

# Make the HMI bridge importable without the UI venv.
# `app.services.__init__` references `app.services.runtime_bridge`, so the
# parent of `app` (`ui-v10`) must be on sys.path, not `ui-v10/app`.
_UI_ROOT = _PROJECT_ROOT / "ui-v10"
if str(_UI_ROOT) not in sys.path:
    sys.path.insert(0, str(_UI_ROOT))

from app.services.runtime_bridge import CommandResult, RuntimeBridge  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_state(
    *,
    evidence: str = "off",
    memory: str = "off",
    voice: str = "off",
    conversation: str = "off",
    model: str = "local-lucy-llama31",
) -> dict[str, Any]:
    return {
        "active_model": model,
        "approval_required": False,
        "augmentation_policy": "disabled",
        "augmented_provider": "wikipedia",
        "conversation": conversation,
        "evidence": evidence,
        "gemma4_smart_routing": "off",
        "last_updated": "2026-07-30T00:00:00Z",
        "learner": "off",
        "memory": memory,
        "mode": "auto",
        "model": model,
        "profile": "lucy-v11",
        "schema_version": 1,
        "self_analysis_mode": "off",
        "status": "ready",
        "voice": voice,
        "voice_tts_chunk_pause_ms": 56,
    }


def _make_fake_runtime_request(captured: dict[str, Any]) -> types.ModuleType:
    """Return a fake `runtime_request` module that records calls."""
    fake = types.SimpleNamespace()

    def submit_request(
        request_text: str,
        *,
        augmented_direct_once: bool = False,
        self_review: bool = False,
        surface: str = "cli",
        context: dict[str, Any] | None = None,
        model: str | None = None,
        persist: bool = True,
    ) -> dict[str, Any]:
        captured["calls"].append(
            {
                "request_text": request_text,
                "augmented_direct_once": augmented_direct_once,
                "self_review": self_review,
                "surface": surface,
                "context": context,
                "model": model,
                "persist": persist,
            }
        )
        return {
            "request_id": "test-request-001",
            "status": "completed",
            "response_text": f"Echo: {request_text}",
            "error": "",
            "route": {"mode": "LOCAL", "reason": "local_sufficient", "confidence": 0.95},
            "outcome": {"outcome_code": "answered", "hint": "none"},
            "model_used": model or "local-lucy-llama31",
        }

    fake.submit_request = submit_request  # type: ignore[attr-defined]
    return fake  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def hmi_bridge(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> RuntimeBridge:
    """Return a `RuntimeBridge` wired to a disposable namespace/state file."""
    namespace_root = tmp_path / "namespace"
    state_dir = namespace_root / "state"
    state_dir.mkdir(parents=True)
    state_file = state_dir / "current_state.json"
    state_file.write_text(json.dumps(_minimal_state()), encoding="utf-8")

    # Authority contract: point at v11, disable strict contract checks.
    monkeypatch.setenv("LUCY_RUNTIME_AUTHORITY_ROOT", str(_PROJECT_ROOT))
    monkeypatch.setenv("LUCY_UI_ROOT", str(_PROJECT_ROOT / "ui-v10"))
    monkeypatch.setenv("LUCY_RUNTIME_NAMESPACE_ROOT", str(namespace_root))
    monkeypatch.setenv("LUCY_RUNTIME_STATE_FILE", str(state_file))
    monkeypatch.setenv("LUCY_RUNTIME_CONTRACT_REQUIRED", "0")
    monkeypatch.setenv("LUCY_DISABLE_BACKGROUND_WARMUP", "1")

    # Ensure pytest marker disables background warmup even if the above var is
    # forgotten; PYTEST_CURRENT_TEST is set by pytest itself.
    assert "PYTEST_CURRENT_TEST" in os.environ

    # Inject a fake `runtime_request` module so no backend or Ollama runs.
    # Use monkeypatch.setitem so the real module is restored after the test;
    # otherwise later tests that import `runtime_request` see the fake.
    captured: dict[str, Any] = {"calls": []}
    fake_runtime_request = _make_fake_runtime_request(captured)
    monkeypatch.setitem(sys.modules, "runtime_request", fake_runtime_request)

    bridge = RuntimeBridge()
    # Prevent any accidental Ollama unload/load calls during the submit path.
    monkeypatch.setattr(bridge, "_unload_other_ollama_models", lambda keep_model: None)
    monkeypatch.setattr(bridge, "_warmup_ollama_model", lambda model: None)

    # Surface the captured calls on the bridge for assertions.
    bridge._test_captured = captured  # type: ignore[attr-defined]
    return bridge


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_hmi_submit_returns_valid_payload(hmi_bridge: RuntimeBridge) -> None:
    """S12-HMI-001: trivial local query returns ok with valid payload."""
    result = hmi_bridge.run_action("submit_request", "hello")
    assert isinstance(result, CommandResult)
    assert result.status == "ok"
    assert result.returncode == 0
    assert result.payload is not None
    assert result.payload["route"]["mode"] == "LOCAL"
    assert result.payload["outcome"]["outcome_code"] == "answered"
    assert result.payload["request_id"]

    # Verify the backend was invoked through the HMI surface.
    calls = hmi_bridge._test_captured["calls"]  # type: ignore[attr-defined]
    assert len(calls) == 1
    assert calls[0]["surface"] == "hmi"
    assert calls[0]["request_text"] == "hello"


def test_hmi_state_propagation_evidence(hmi_bridge: RuntimeBridge, tmp_path: Path) -> None:
    """S12-HMI-002: evidence=on is propagated to LUCY_EVIDENCE_ENABLED=1."""
    state_file = Path(os.environ["LUCY_RUNTIME_STATE_FILE"])
    state = json.loads(state_file.read_text(encoding="utf-8"))
    state["evidence"] = "on"
    state_file.write_text(json.dumps(state), encoding="utf-8")

    result = hmi_bridge.run_action("submit_request", "hello")
    assert result.status == "ok"
    assert os.environ.get("LUCY_EVIDENCE_ENABLED") == "1"
    assert os.environ.get("LUCY_ENABLE_INTERNET") == "1"


def test_hmi_voice_disabled_does_not_invoke_voice(hmi_bridge: RuntimeBridge) -> None:
    """S12-HMI-003: voice=off prevents voice invocation and still returns text."""
    state_file = Path(os.environ["LUCY_RUNTIME_STATE_FILE"])
    state = json.loads(state_file.read_text(encoding="utf-8"))
    state["voice"] = "off"
    state_file.write_text(json.dumps(state), encoding="utf-8")

    result = hmi_bridge.run_action("submit_request", "hello")
    assert result.status == "ok"
    assert os.environ.get("LUCY_VOICE_ENABLED") == "0"
    assert result.stdout == "Echo: hello"


def test_hmi_empty_submit_rejected(hmi_bridge: RuntimeBridge) -> None:
    """S12-HMI-004: empty submit text returns unavailable."""
    result = hmi_bridge.run_action("submit_request", "   ")
    assert result.status == "unavailable"
    assert result.stderr == "empty submit text"
    assert result.payload is None

    calls = hmi_bridge._test_captured["calls"]  # type: ignore[attr-defined]
    assert calls == []


def test_hmi_backend_failure_translated(hmi_bridge: RuntimeBridge, monkeypatch: pytest.MonkeyPatch) -> None:
    """S12-HMI-005: backend failure is translated into CommandResult."""
    fake = sys.modules["runtime_request"]

    def failing_submit(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("simulated backend failure")

    monkeypatch.setattr(fake, "submit_request", failing_submit)

    result = hmi_bridge.run_action("submit_request", "hello")
    assert result.status == "failed"
    assert result.returncode == 1
    assert "simulated backend failure" in result.stderr


def test_hmi_model_selection_passed_to_backend(hmi_bridge: RuntimeBridge) -> None:
    """S12-HMI-006: selected model is passed to submit_request."""
    state_file = Path(os.environ["LUCY_RUNTIME_STATE_FILE"])
    state = json.loads(state_file.read_text(encoding="utf-8"))
    state["model"] = "local-lucy-gemma4"
    state_file.write_text(json.dumps(state), encoding="utf-8")

    result = hmi_bridge.run_action("submit_request", "hello")
    assert result.status == "ok"

    calls = hmi_bridge._test_captured["calls"]  # type: ignore[attr-defined]
    assert len(calls) == 1
    assert calls[0]["model"] == "local-lucy-gemma4"
