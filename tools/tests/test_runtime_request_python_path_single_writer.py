#!/usr/bin/env python3
"""Regression guard against double-writing request history.

The Python-native router (tools/router_py) already persists
last_request_result.json and request_history.jsonl via StateWriter.
When runtime_request.submit_request() also persists for the Python path,
every request appears twice in history.  These tests prove that a backend
which has already persisted is not persisted again by submit_request().
"""

from __future__ import annotations

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


def test_python_backend_marker_skips_runtime_persistence(monkeypatch, tmp_path):
    """When the backend sets _state_persisted, submit_request must not write again."""
    calls = {"persist": 0, "history": 0}

    def fake_run_backend_submit(*, request_text, **kwargs):
        payload = _minimal_payload(request_text)
        payload["_state_persisted"] = True
        return payload

    monkeypatch.setattr(runtime_request, "run_backend_submit", fake_run_backend_submit)

    def fake_persist(result_file, payload):
        calls["persist"] += 1

    monkeypatch.setattr(runtime_request, "persist_payload", fake_persist)

    def fake_append(history_file, payload):
        calls["history"] += 1

    monkeypatch.setattr(runtime_request, "append_history_entry", fake_append)

    result = runtime_request.submit_request("hello python backend", persist=True)

    # The internal marker should not leak out of submit_request.
    assert "_state_persisted" not in result
    assert calls["persist"] == 0, "runtime_request persisted result for already-persisted backend"
    assert calls["history"] == 0, "runtime_request appended history for already-persisted backend"


def test_chat_bin_backend_without_marker_persists_once(monkeypatch, tmp_path):
    """A backend that does not set _state_persisted is still persisted by submit_request."""
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
