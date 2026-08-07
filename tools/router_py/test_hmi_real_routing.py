#!/usr/bin/env python3
"""HMI-level routing regression tests using the real classifier and pipeline.

These tests exercise the same Python-native backend path that RuntimeBridge
uses (`runtime_request.submit_request`), but with a temporary namespace and
network calls blocked. They verify that restaurant/location queries are not
misrouted to TIME or WEATHER and that location anaphora is resolved before
web routes attempt to fetch.

These are intentionally not mocked at the backend level; they catch defects
that only appear when routing decisions are made from the real classifier.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from router_py.model_residency import assert_single_local_lucy_model

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
if str(_PROJECT_ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT / "tools"))


@pytest.fixture
def temp_namespace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create an isolated runtime namespace and memory DB."""
    namespace = tmp_path / "namespace"
    state_dir = namespace / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    db_path = state_dir / "memory.db"

    monkeypatch.setenv("LUCY_RUNTIME_NAMESPACE_ROOT", str(namespace))
    monkeypatch.setenv("LUCY_MEMORY_DB_PATH", str(db_path))
    # Keep evidence enabled so restaurant queries can route to AUGMENTED;
    # outbound HTTP is blocked by the captured_urls fixture, so no real
    # network traffic leaves the test.
    monkeypatch.setenv("LUCY_EVIDENCE_ENABLED", "1")
    monkeypatch.setenv("LUCY_ENABLE_INTERNET", "1")
    monkeypatch.setenv("LUCY_DISABLE_BACKGROUND_WARMUP", "1")

    # Initialise the memory schema so location facts can be stored/retrieved.
    import tools.memory.memory_service as memory_service

    conn = sqlite3.connect(str(db_path))
    memory_service._ensure_schema(conn)
    conn.close()

    return namespace


@pytest.fixture
def captured_urls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Block outbound HTTP and capture every URL the backend tries to fetch."""
    urls: list[str] = []

    def _blocking_urlopen(req: Any, *args: Any, **kwargs: Any) -> Any:
        url = req.full_url if hasattr(req, "full_url") else str(req)
        urls.append(url)
        raise urllib.error.URLError("network disabled in test")

    monkeypatch.setattr(urllib.request, "urlopen", _blocking_urlopen)
    return urls


@pytest.fixture(autouse=True)
def _mock_ollama_ps(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep residency checks deterministic without a live Ollama daemon."""
    monkeypatch.setattr(
        "router_py.model_residency.list_loaded_ollama_models",
        lambda: [],
    )


@pytest.fixture
def submit() -> Any:
    from runtime_request import submit_request

    return submit_request


class TestHmiRestaurantRouting:
    """Restaurant/dining queries must route to AUGMENTED, not TIME/WEATHER."""

    def test_near_me_restaurant_routes_augmented(
        self,
        temp_namespace: Path,
        captured_urls: list[str],
        submit: Any,
    ) -> None:
        payload = submit(
            "Hi Lucy, what is a good restaurant near me that is open on Saturdays?",
            surface="hmi",
            persist=False,
        )
        route = payload.get("route", {})
        assert route.get("mode") == "AUGMENTED", route
        assert route.get("reason") == "router_restaurant_dining_guard", route
        assert route.get("mode") not in ("TIME", "WEATHER")

    def test_today_restaurant_typo_routes_augmented(
        self,
        temp_namespace: Path,
        captured_urls: list[str],
        submit: Any,
    ) -> None:
        payload = submit(
            "Search for restraunts in my area that are open today.",
            surface="hmi",
            persist=False,
        )
        route = payload.get("route", {})
        assert route.get("mode") == "AUGMENTED", route
        assert route.get("reason") == "router_restaurant_dining_guard", route
        assert route.get("mode") not in ("TIME", "WEATHER")

    def test_location_restaurant_routes_augmented(
        self,
        temp_namespace: Path,
        captured_urls: list[str],
        submit: Any,
    ) -> None:
        payload = submit(
            "I am looking for a good restraunt open today near kibbutz Magal.",
            surface="hmi",
            persist=False,
        )
        route = payload.get("route", {})
        assert route.get("mode") == "AUGMENTED", route
        assert route.get("reason") == "router_restaurant_dining_guard", route
        assert route.get("mode") not in ("TIME", "WEATHER")


class TestHmiLocationAnaphora:
    """Stored location facts should resolve anaphoric location references."""

    def test_location_fact_stored_and_resolved(
        self,
        temp_namespace: Path,
        captured_urls: list[str],
        submit: Any,
    ) -> None:
        # First, store the location.
        payload = submit("I live in Kibbutz Magal, Israel.", surface="hmi", persist=False)
        assert payload.get("route", {}).get("mode") == "LOCAL"
        assert_single_local_lucy_model("after test_location_fact_stored_and_resolved")

        # Then ask a location-aware restaurant question.
        submit(
            "Search for restaurants in my area that are open today.",
            surface="hmi",
            persist=False,
        )
        # The anaphora resolver should have replaced "in my area" with the
        # stored location before the web route attempted to fetch. The resolved
        # query appears in the URLs captured by the network blocker.
        decoded = " ".join(urllib.parse.unquote(u) for u in captured_urls)
        assert "Kibbutz Magal" in decoded, captured_urls
