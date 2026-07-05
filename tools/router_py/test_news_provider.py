#!/usr/bin/env python3
"""Unit tests for RSSNewsProvider recency and cross-check behaviour."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from news_provider import (
    RSSNewsProvider,
    _article_is_stale,
    _detect_source_disagreement,
    _query_asks_for_history,
)


def _make_article(title: str, source: str, published: str) -> dict:
    return {
        "title": title,
        "description": "",
        "url": "",
        "source": source,
        "published": published,
        "time_ago": "recently",
        "timestamp": published,
        "_sort_dt": datetime.strptime(published, "%a, %d %b %Y %H:%M:%S %z"),
    }


def test_query_asks_for_history():
    assert _query_asks_for_history("history of the cold war")
    assert _query_asks_for_history("what happened in 2020")
    assert _query_asks_for_history("events during the pandemic")
    assert _query_asks_for_history("past economic crises")
    assert _query_asks_for_history("old news about trump")
    assert not _query_asks_for_history("latest world news")
    assert not _query_asks_for_history("what is happening in gaza today")


def test_article_is_stale():
    recent = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%a, %d %b %Y %H:%M:%S %z")
    old = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%a, %d %b %Y %H:%M:%S %z")
    assert not _article_is_stale(recent, days=7)
    assert _article_is_stale(old, days=7)


def test_recency_filter_drops_old_articles_for_latest_news():
    articles = [
        _make_article("Fresh headline", "Source A", _days_ago(1)),
        _make_article("Stale headline", "Source B", _days_ago(10)),
    ]
    filtered = RSSNewsProvider._filter_by_recency(articles, "latest world news")
    titles = {a["title"] for a in filtered}
    assert "Fresh headline" in titles
    assert "Stale headline" not in titles


def test_recency_filter_keeps_old_articles_for_history_query():
    articles = [
        _make_article("Fresh headline", "Source A", _days_ago(1)),
        _make_article("Stale headline", "Source B", _days_ago(10)),
    ]
    filtered = RSSNewsProvider._filter_by_recency(articles, "history of the cold war")
    titles = {a["title"] for a in filtered}
    assert "Fresh headline" in titles
    assert "Stale headline" in titles


def test_detect_region_handles_israeli_typos():
    assert "middle_east" in RSSNewsProvider._detect_region("Whats the latest Iraeli News?")
    assert "middle_east" in RSSNewsProvider._detect_region("latest news from Isreal")
    assert "middle_east" in RSSNewsProvider._detect_region("what's happening in Jerusalem?")
    assert "middle_east" not in RSSNewsProvider._detect_region("latest world news")


def test_detect_source_disagreement_flags_conflicting_titles():
    articles = [
        {"title": "Israel confirms ceasefire with Hamas", "source": "A"},
        {"title": "Hamas denies ceasefire deal", "source": "B"},
    ]
    assert _detect_source_disagreement(articles)


def test_detect_source_disagreement_no_conflict():
    articles = [
        {"title": "Israel reports airstrikes in Gaza", "source": "A"},
        {"title": "Gaza hospitals face shortages", "source": "B"},
    ]
    assert not _detect_source_disagreement(articles)


def test_detect_source_disagreement_single_source():
    articles = [
        {"title": "Israel reports airstrikes in Gaza", "source": "A"},
    ]
    assert not _detect_source_disagreement(articles)


def _days_ago(n: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=n)
    return dt.strftime("%a, %d %b %Y %H:%M:%S %z")
