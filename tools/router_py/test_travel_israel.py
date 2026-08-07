#!/usr/bin/env python3
"""Tests for Israel-specific travel destination extraction and fetching."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from unverified_context_trusted import (
    _extract_travel_destination,
    _fetch_israel_travel_summary,
    _format_travel_response,
)


def test_israel_destination_extraction():
    assert _extract_travel_destination("recommend places to visit in Israel") == "Israel"
    assert _extract_travel_destination("what should I see in Jerusalem?") == "Jerusalem"


def test_things_to_do_in_tel_aviv():
    assert _extract_travel_destination("things to do in Tel Aviv") == "Tel Aviv"


def test_eretz_variant_maps_to_israel():
    assert _extract_travel_destination("visit Eretz Israel") == "Israel"


def test_known_israel_destinations():
    assert _extract_travel_destination("guide to Haifa") == "Haifa"
    assert _extract_travel_destination("what to see in Eilat") == "Eilat"
    assert _extract_travel_destination("places to visit in Galilee") == "Galilee"
    assert _extract_travel_destination("things to do in the Dead Sea") == "Dead Sea"
    assert _extract_travel_destination("travel to the Negev") == "Negev"


def test_non_travel_israel_query_returns_none():
    assert _extract_travel_destination("News from Israel") is None


def test_israel_fetcher_uses_allowlisted_source(monkeypatch, tmp_path):
    def _fake_fetch(url, timeout):
        return "Israel tourism content"

    monkeypatch.setattr("unverified_context_trusted._fetch_url_text", _fake_fetch)
    monkeypatch.setattr(
        "unverified_context_trusted._travel_cache_path", lambda: tmp_path / "travel_cache.json"
    )
    result = _fetch_israel_travel_summary("Israel")
    assert result is not None
    assert "israel.travel" in result["source"] or "goisrael" in result["source"]


def test_israel_fetcher_prefers_opengraph_description(monkeypatch, tmp_path):
    html = (
        '<html><head>'
        '<meta property="og:description" content="Official Israel tourism overview">'
        '</head><body>Other content</body></html>'
    )
    monkeypatch.setattr("unverified_context_trusted._fetch_url_text", lambda url, timeout: html)
    monkeypatch.setattr(
        "unverified_context_trusted._travel_cache_path", lambda: tmp_path / "travel_cache.json"
    )
    result = _fetch_israel_travel_summary("Jerusalem")
    assert result is not None
    assert result["text"] == "Official Israel tourism overview"


def test_israel_fetcher_caches_result(monkeypatch, tmp_path):
    calls = []

    def _fake_fetch(url, timeout):
        calls.append(url)
        return "Israel tourism content"

    monkeypatch.setattr("unverified_context_trusted._fetch_url_text", _fake_fetch)
    monkeypatch.setattr(
        "unverified_context_trusted._travel_cache_path", lambda: tmp_path / "travel_cache.json"
    )
    result1 = _fetch_israel_travel_summary("Israel")
    result2 = _fetch_israel_travel_summary("Israel")
    assert result1 == result2
    assert len(calls) == 1


def test_israel_fetcher_cache_respects_ttl(monkeypatch, tmp_path):
    monkeypatch.setattr("unverified_context_trusted._fetch_url_text", lambda url, timeout: "fresh")
    monkeypatch.setattr(
        "unverified_context_trusted._travel_cache_path", lambda: tmp_path / "travel_cache.json"
    )
    # Pre-populate cache with an expired entry
    cache_path = tmp_path / "travel_cache.json"
    cache_path.write_text(
        json.dumps(
            {
                "Israel|https://israel.travel/en/israel": {
                    "timestamp": time.time() - 90000,
                    "data": {"source": "https://israel.travel/en/israel", "text": "stale"},
                }
            }
        )
    )
    result = _fetch_israel_travel_summary("Israel")
    assert result is not None
    assert result["text"] == "fresh"


def test_format_travel_response_uses_israel_source(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "unverified_context_trusted._fetch_url_text", lambda url, timeout: "Israel tourism content"
    )
    monkeypatch.setattr(
        "unverified_context_trusted._travel_cache_path", lambda: tmp_path / "travel_cache.json"
    )
    content, metadata = _format_travel_response(
        ["israel.travel", "goisrael.com", "wikivoyage.org"],
        "recommend places to visit in Israel",
        include_metadata=True,
    )
    assert "Israel Ministry of Tourism" in content
    assert "israel.travel" in content or "goisrael" in content
    assert metadata["LIVE_FETCH_STATUS"] == "success"


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
