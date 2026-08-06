#!/usr/bin/env python3
"""Regression guard for request-history persistence.

The Python-native router (tools/router_py) writes last_request_result.json and
request_history.jsonl for outcomes produced by the ExecutionEngine, but it does
not write them for early-exit outcomes such as operator_blocked or
feedback_acknowledged.  runtime_request.submit_request() is therefore
responsible for persisting every payload it receives.  The history writer
skips duplicate request_ids, so an outcome that the engine already wrote is
not duplicated.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

import runtime_request


def _minimal_payload(request_text: str) -> dict:
    """Build the smallest valid payload returned by a backend submit path."""
    return {
        "accepted": True,
        "authority": runtime_request.build_authority_payload(),
        "completed_at": "2026-07-24T12:00:00Z",
        "control_state": {
            "augmentation_policy": "fallback_only",
            "augmented_provider": "wikipedia",
            "conversation": "off",
            "evidence": "off",
            "memory": "off",
            "mode": "auto",
            "model": "local-lucy",
            "profile": "lucy-v11",
            "voice": "off",
        },
        "error": "",
        "outcome": {
            "action_hint": "",
            "final_mode": "LOCAL",
            "outcome_code": "answered",
            "requested_mode": "",
            "trust_class": "local",
        },
        "request_id": f"test-{request_text[:20]}",
        "request_text": request_text,
        "response_text": f"reply to {request_text}",
        "route": {
            "mode": "LOCAL",
            "selected_route": "LOCAL",
            "final_mode": "LOCAL",
            "query": request_text,
            "reason": "router_local",
            "session_id": "test-session",
            "utc": "2026-07-24T12:00:00Z",
        },
        "status": "completed",
    }


def test_python_backend_persists_once_via_wrapper(monkeypatch, tmp_path):
    """submit_request() persists a Python-backend payload itself."""
    calls = {"persist": 0, "history": 0}

    def fake_run_backend_submit(*, request_text, **kwargs):
        return _minimal_payload(request_text)

    monkeypatch.setattr(runtime_request, "run_backend_submit", fake_run_backend_submit)

    def fake_persist(result_file, payload):
        calls["persist"] += 1

    monkeypatch.setattr(runtime_request, "persist_payload", fake_persist)

    def fake_append(history_file, payload):
        calls["history"] += 1

    monkeypatch.setattr(runtime_request, "append_history_entry", fake_append)

    result = runtime_request.submit_request("hello python backend", persist=True)

    assert "_state_persisted" not in result
    assert calls["persist"] == 1, "runtime_request should persist Python-backend result"
    assert calls["history"] == 1, "runtime_request should append Python-backend history"


def test_python_backend_does_not_duplicate_history_when_engine_already_wrote(tmp_path):
    """If the engine already wrote the same request_id, wrapper appends nothing."""
    request_text = "hello python backend dedup"
    payload = _minimal_payload(request_text)
    request_id = payload["request_id"]

    namespace = tmp_path / "ns"
    namespace.mkdir()
    state_dir = namespace / "state"
    state_dir.mkdir()
    history_file = state_dir / "request_history.jsonl"
    result_file = state_dir / "last_request_result.json"

    # Simulate an engine write that already happened.
    entry = runtime_request.build_history_entry(payload)
    history_file.write_text(json.dumps(entry, sort_keys=True) + "\n", encoding="utf-8")

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("LUCY_RUNTIME_NAMESPACE_ROOT", str(namespace))
    monkeypatch.setenv("LUCY_RUNTIME_REQUEST_RESULT_FILE", str(result_file))
    monkeypatch.setenv("LUCY_RUNTIME_REQUEST_HISTORY_FILE", str(history_file))

    def fake_run_backend_submit(*, request_text, **kwargs):
        return payload

    monkeypatch.setattr(runtime_request, "run_backend_submit", fake_run_backend_submit)

    try:
        runtime_request.submit_request(request_text, persist=True)
    finally:
        monkeypatch.undo()

    lines = [line.strip() for line in history_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 1, f"expected one history entry, got {len(lines)}"
    parsed = json.loads(lines[0])
    assert parsed["request_id"] == request_id


def test_chat_bin_backend_without_marker_persists_once(monkeypatch, tmp_path):
    """A backend that does not set _state_persisted is persisted by submit_request."""
    calls = {"persist": 0, "history": 0}

    def fake_run_backend_submit(*, request_text, **kwargs):
        return _minimal_payload(request_text)

    monkeypatch.setattr(runtime_request, "run_backend_submit", fake_run_backend_submit)

    def fake_persist(result_file, payload):
        calls["persist"] += 1

    monkeypatch.setattr(runtime_request, "persist_payload", fake_persist)

    def fake_append(history_file, payload):
        calls["history"] += 1

    monkeypatch.setattr(runtime_request, "append_history_entry", fake_append)

    runtime_request.submit_request("hello chat bin", persist=True)

    assert calls["persist"] == 1, "runtime_request should persist for non-marked backend"
    assert calls["history"] == 1, "runtime_request should append history for non-marked backend"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
