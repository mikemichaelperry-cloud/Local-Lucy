"""Characterization tests for StateManager public API.

These tests must pass before and after the state_manager.py split.
They use a temporary namespace root so they do not pollute global state.
"""
from __future__ import annotations

import os

import pytest


@pytest.fixture
def tmp_state_manager(tmp_path):
    """Return a StateManager backed by a temp namespace DB."""
    db_path = tmp_path / "state" / "lucy_state.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    old = os.environ.get("LUCY_STATE_DB")
    os.environ["LUCY_STATE_DB"] = str(db_path)
    try:
        from router_py.state import StateManager, get_state_manager, init_database

        assert init_database(db_path) is True
        sm = get_state_manager("characterization")
        yield sm
        sm.close()
    finally:
        if old is None:
            os.environ.pop("LUCY_STATE_DB", None)
        else:
            os.environ["LUCY_STATE_DB"] = old


def test_write_and_read_last_route(tmp_state_manager):
    assert tmp_state_manager.write_route(
        {"intent": "search", "confidence": 0.95, "strategy": "ml", "metadata": {"q": "x"}}
    )
    route = tmp_state_manager.read_last_route()
    assert route is not None
    assert route["intent"] == "search"
    assert route["confidence"] == pytest.approx(0.95)
    assert route["metadata"] == {"q": "x"}


def test_read_routes_pagination(tmp_state_manager):
    for i in range(3):
        assert tmp_state_manager.write_route(
            {"intent": f"intent_{i}", "confidence": 0.5 + i * 0.1}
        )
    routes = tmp_state_manager.read_routes(limit=2, offset=0)
    assert len(routes) == 2
    assert routes[0]["intent"] == "intent_2"


def test_write_and_read_last_outcome(tmp_state_manager):
    assert tmp_state_manager.write_outcome(
        {"success": True, "duration_ms": 150, "result": {"items": 5}}
    )
    outcome = tmp_state_manager.read_last_outcome()
    assert outcome is not None
    assert outcome["success"] is True
    assert outcome["result"] == {"items": 5}


def test_write_batch(tmp_state_manager):
    assert tmp_state_manager.write_batch(
        {"intent": "batch", "confidence": 0.8},
        {"success": True, "duration_ms": 10, "result": {}},
    )
    assert tmp_state_manager.read_last_route()["intent"] == "batch"
    assert tmp_state_manager.read_last_outcome()["success"] is True


def test_read_outcomes_filtering(tmp_state_manager):
    assert tmp_state_manager.write_outcome({"success": True})
    assert tmp_state_manager.write_outcome({"success": False})
    outcomes = tmp_state_manager.read_outcomes(success_only=True, limit=10)
    assert len(outcomes) == 1
    assert outcomes[0]["success"] is True


def test_session_lifecycle(tmp_state_manager):
    assert tmp_state_manager.write_session("s1", {"a": 1}, ttl_seconds=300)
    assert tmp_state_manager.read_session("s1") == {"a": 1}
    assert tmp_state_manager.delete_session("s1") is True
    assert tmp_state_manager.read_session("s1") is None


def test_session_expiration(tmp_state_manager):
    assert tmp_state_manager.write_session("s2", {"a": 1}, ttl_seconds=-1)
    assert tmp_state_manager.read_session("s2") is None


def test_lock_lifecycle(tmp_state_manager):
    assert tmp_state_manager.acquire_lock("lk", timeout=1.0) is True
    assert tmp_state_manager.is_locked("lk") is True
    assert tmp_state_manager.release_lock("lk") is True
    assert tmp_state_manager.is_locked("lk") is False


def test_telemetry(tmp_state_manager):
    assert tmp_state_manager.record_telemetry("evt", {"metric": 1})
    summary = tmp_state_manager.get_telemetry_summary()
    assert summary["total_count"] >= 1
    assert "evt" in summary["event_breakdown"]


def test_health_check(tmp_state_manager):
    health = tmp_state_manager.health_check()
    assert health["connected"] is True
    assert "routes" in health["tables"]


def test_context_manager(tmp_path):
    db_path = tmp_path / "state" / "lucy_state.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    old = os.environ.get("LUCY_STATE_DB")
    os.environ["LUCY_STATE_DB"] = str(db_path)
    try:
        from router_py.state import StateManager

        with StateManager("ctx") as sm:
            assert sm.health_check()["connected"] is True
    finally:
        if old is None:
            os.environ.pop("LUCY_STATE_DB", None)
        else:
            os.environ["LUCY_STATE_DB"] = old
