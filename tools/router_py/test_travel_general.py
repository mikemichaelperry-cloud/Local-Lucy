#!/usr/bin/env python3
"""Tests for generalised Wikivoyage-based travel fetcher."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from unverified_context_trusted import (
    _TRAVEL_DESTINATION_MAP,
    _extract_travel_destination,
    _fetch_wikivoyage_summary,
    _format_travel_response,
)


def test_wikivoyage_general_destination(monkeypatch):
    monkeypatch.setattr(
        "unverified_context_trusted._fetch_json",
        lambda url, timeout: {"extract": "Japan travel guide", "title": "Japan"},
    )
    result = _fetch_wikivoyage_summary("Japan")
    assert result is not None
    assert "Japan" in result["text"]
    assert result["title"] == "Japan"


def test_wikivoyage_fetcher_uses_fetch_json(monkeypatch):
    calls = []

    def _fake_fetch_json(url, timeout):
        calls.append((url, timeout))
        return {"extract": "France travel guide", "title": "France"}

    monkeypatch.setattr("unverified_context_trusted._fetch_json", _fake_fetch_json)
    result = _fetch_wikivoyage_summary("France")
    assert result is not None
    assert len(calls) == 1
    assert calls[0][0] == "https://en.wikivoyage.org/api/rest_v1/page/summary/France"
    assert calls[0][1] == 10


def test_wikivoyage_fetcher_returns_none_without_extract(monkeypatch):
    monkeypatch.setattr(
        "unverified_context_trusted._fetch_json",
        lambda url, timeout: {"title": "France"},
    )
    result = _fetch_wikivoyage_summary("France")
    assert result is None


def test_wikivoyage_fetcher_replaces_spaces_with_underscores(monkeypatch):
    calls = []

    def _fake_fetch_json(url, timeout):
        calls.append(url)
        return {"extract": "New York City travel guide", "title": "New York City"}

    monkeypatch.setattr("unverified_context_trusted._fetch_json", _fake_fetch_json)
    result = _fetch_wikivoyage_summary("New York City")
    assert result is not None
    assert calls[0] == "https://en.wikivoyage.org/api/rest_v1/page/summary/New_York_City"


def test_non_israel_destination_uses_wikivoyage_primary(monkeypatch):
    israel_calls = []

    def _fake_israel_fetch(destination):
        israel_calls.append(destination)
        return None

    monkeypatch.setattr(
        "unverified_context_trusted._fetch_israel_travel_summary", _fake_israel_fetch
    )
    monkeypatch.setattr(
        "unverified_context_trusted._fetch_json",
        lambda url, timeout: {"extract": "France travel guide", "title": "France"},
    )

    content, metadata = _format_travel_response(
        ["wikivoyage.org"],
        "Best places to visit in France",
        include_metadata=True,
    )
    assert "France travel guide" in content
    assert "Wikivoyage" in content
    assert metadata["LIVE_FETCH_STATUS"] == "success"
    assert len(israel_calls) == 0


def test_israel_destination_prefers_israel_source(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "unverified_context_trusted._fetch_url_text",
        lambda url, timeout: "Israel tourism content",
    )
    monkeypatch.setattr(
        "unverified_context_trusted._travel_cache_path",
        lambda: tmp_path / "travel_cache.json",
    )
    content, metadata = _format_travel_response(
        ["israel.travel", "goisrael.com", "wikivoyage.org"],
        "recommend places to visit in Israel",
        include_metadata=True,
    )
    assert "Israel Ministry of Tourism" in content
    assert metadata["LIVE_FETCH_STATUS"] == "success"


def test_israel_destination_falls_back_to_wikivoyage(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "unverified_context_trusted._fetch_url_text", lambda url, timeout: None
    )
    monkeypatch.setattr(
        "unverified_context_trusted._travel_cache_path",
        lambda: tmp_path / "travel_cache.json",
    )
    monkeypatch.setattr(
        "unverified_context_trusted._fetch_json",
        lambda url, timeout: {"extract": "Israel travel guide", "title": "Israel"},
    )

    content, metadata = _format_travel_response(
        ["israel.travel", "goisrael.com", "wikivoyage.org"],
        "recommend places to visit in Israel",
        include_metadata=True,
    )
    assert "Israel travel guide" in content
    assert "Wikivoyage" in content
    assert metadata["LIVE_FETCH_STATUS"] == "success"


def test_known_destination_wikivoyage_failure_asks_for_region(monkeypatch):
    monkeypatch.setattr("unverified_context_trusted._fetch_json", lambda url, timeout: None)
    monkeypatch.setattr(
        "unverified_context_trusted._fetch_israel_travel_summary",
        lambda destination: None,
    )

    content, metadata = _format_travel_response(
        ["wikivoyage.org"],
        "Travel guide to France",
        include_metadata=True,
    )
    assert "specify" in content.lower() or "country" in content.lower() or "region" in content.lower()
    assert metadata["LIVE_FETCH_STATUS"] == "failed"


def test_unknown_destination_returns_safe_fallback():
    content, metadata = _format_travel_response(
        ["wikivoyage.org"],
        "What is the weather today?",
        include_metadata=True,
    )
    assert "country" in content.lower() or "region" in content.lower()
    assert metadata["LIVE_FETCH_STATUS"] == "skipped"


def test_destination_map_includes_required_countries():
    required = {
        "uk",
        "france",
        "germany",
        "italy",
        "spain",
        "japan",
        "thailand",
        "usa",
        "canada",
        "australia",
        "egypt",
        "greece",
    }
    assert required.issubset(set(_TRAVEL_DESTINATION_MAP.keys()))


def test_destination_extraction_for_new_countries():
    assert _extract_travel_destination("Best places to visit in France") == "France"
    assert _extract_travel_destination("Travel guide to Germany") == "Germany"
    assert _extract_travel_destination("What should I see in Italy?") == "Italy"
    assert _extract_travel_destination("Where should I go in Spain?") == "Spain"
    assert _extract_travel_destination("Places to visit in Canada") == "Canada"


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
