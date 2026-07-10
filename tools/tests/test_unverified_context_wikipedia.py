"""Regression tests for the Wikipedia evidence provider."""

from __future__ import annotations

import sys
import urllib.parse
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(ROOT / "tools"))

import unverified_context_wikipedia as wiki


def _direct_summary_title(url: str) -> tuple[str, str] | None:
    parsed = urllib.parse.urlparse(url)
    if parsed.path.startswith("/api/rest_v1/page/summary/"):
        lang = parsed.netloc.split(".")[0]
        title = urllib.parse.unquote(parsed.path[len("/api/rest_v1/page/summary/") :])
        return lang, title
    return None


def _search_query(url: str) -> tuple[str, str] | None:
    parsed = urllib.parse.urlparse(url)
    if parsed.path == "/w/api.php":
        lang = parsed.netloc.split(".")[0]
        qs = urllib.parse.parse_qs(parsed.query)
        return lang, qs.get("srsearch", [None])[0]
    return None


def _make_http_mock(
    direct_payloads: dict[tuple[str, str], dict | None],
    search_results: dict[tuple[str, str], list[dict]],
):
    """Return a fake _http_json backed by *direct_payloads* and *search_results*."""

    def fake_http(url: str):
        lang_title = _direct_summary_title(url)
        if lang_title is not None:
            payload = direct_payloads.get(lang_title)
            if payload is None:
                raise RuntimeError(f"direct summary not found: {lang_title}")
            return payload

        lang_query = _search_query(url)
        if lang_query is not None:
            return {"query": {"search": search_results.get(lang_query, [])}}

        raise RuntimeError(f"unexpected URL: {url}")

    return fake_http


def test_japan_tourist_attractions_falls_back_to_tourism_in_japan(monkeypatch, tmp_path):
    """Regression for the 'Japan' query returning 'Tourism in China'."""
    monkeypatch.setenv("LUCY_ROOT", str(tmp_path))

    direct = {
        ("en", "main tourist attractions in Japan"): None,
        ("en", "Tourism in Japan"): {
            "extract": "Tourism in Japan is a major industry and contributor to the Japanese economy.",
            "title": "Tourism in Japan",
            "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Tourism_in_Japan"}},
        },
    }
    search = {
        ("en", "main tourist attractions in Japan"): [{"title": "Tourism in China"}],
    }

    with patch.object(wiki, "_http_json", side_effect=_make_http_mock(direct, search)):
        result = wiki.fetch_context("What are the main tourist attractions in Japan?")

    assert result["ok"] is True
    assert result["title"] == "Tourism in Japan"
    assert "Japan" in result["url"]


def test_quantum_computing_direct_summary_accepted(monkeypatch, tmp_path):
    """A clean direct-summary hit should still work."""
    monkeypatch.setenv("LUCY_ROOT", str(tmp_path))

    direct = {
        ("en", "quantum computing"): {
            "extract": "Quantum computing is a type of computation that harnesses quantum mechanics.",
            "title": "Quantum computing",
            "content_urls": {
                "desktop": {"page": "https://en.wikipedia.org/wiki/Quantum_computing"}
            },
        },
    }
    search: dict[tuple[str, str], list[dict]] = {}

    with patch.object(wiki, "_http_json", side_effect=_make_http_mock(direct, search)):
        result = wiki.fetch_context("What is quantum computing?")

    assert result["ok"] is True
    assert result["title"] == "Quantum computing"


def test_extract_place_tail_recognizes_trailing_place():
    assert wiki._extract_place_tail("main tourist attractions in Japan") == "Japan"
    assert wiki._extract_place_tail("capital of France") == "France"
    assert wiki._extract_place_tail("president of the United States") == "United States"


def test_title_matches_query_requires_place_tail():
    assert (
        wiki._title_matches_query("Tourism in Japan", "main tourist attractions in Japan", "Japan")
        is True
    )
    assert (
        wiki._title_matches_query("Tourism in China", "main tourist attractions in Japan", "Japan")
        is False
    )
