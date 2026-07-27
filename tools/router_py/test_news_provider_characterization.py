#!/usr/bin/env python3
"""Characterization tests for the news_provider public API.

These tests must pass before and after the news_provider.py split.
They mock external network calls so they remain fast and deterministic.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from router_py.news import (
    NewsProvider,
    NewsResult,
    RSSNewsProvider,
    fetch_latest_news,
)


def test_news_result_dataclass():
    result = NewsResult(ok=True, text="headline", source="rss")
    assert result.ok is True
    assert result.text == "headline"
    assert result.source == "rss"


@pytest.mark.asyncio
async def test_news_provider_fetch_news_uses_rss_directly():
    expected = NewsResult(ok=True, text="rss news", source="rss")
    with patch.object(
        RSSNewsProvider, "fetch_world_news_async", return_value=expected
    ):
        result = await NewsProvider.fetch_news("latest", for_voice=False)
    assert result.ok is True
    assert result.source == "rss"


def test_fetch_latest_news_returns_text_on_success():
    expected = NewsResult(ok=True, text="plain news", source="rss")
    with patch.object(
        RSSNewsProvider, "fetch_world_news_async", new=AsyncMock(return_value=expected)
    ):
        text = fetch_latest_news("query")
    assert "plain news" in text


def test_fetch_latest_news_returns_error_on_failure():
    expected = NewsResult(ok=False, text="", source="rss", error="network down")
    with patch.object(
        RSSNewsProvider, "fetch_world_news_async", new=AsyncMock(return_value=expected)
    ):
        text = fetch_latest_news("query")
    assert "network down" in text


@pytest.mark.asyncio
async def test_rss_news_provider_format_response_plain():
    articles = [
        {
            "title": "Title A",
            "description": "Desc A",
            "url": "http://example.com/a",
            "source": "Source A",
            "published": "",
            "time_ago": "recently",
            "timestamp": "",
        }
    ]
    text = RSSNewsProvider._format_news_response_plain(articles, "query")
    assert "Title A" in text
    assert "Source A" in text


@pytest.mark.asyncio
async def test_rss_news_provider_format_response_voice():
    articles = [
        {
            "title": "Title A",
            "description": "Desc A",
            "url": "",
            "source": "Source A",
            "published": "",
            "time_ago": "recently",
            "timestamp": "",
        }
    ]
    text = RSSNewsProvider._format_news_response_voice(articles, "query")
    assert "Title A" in text
    assert "Source A" in text


@pytest.mark.asyncio
async def test_rss_news_provider_format_response_html():
    articles = [
        {
            "title": "Title A",
            "description": "Desc A",
            "url": "http://example.com/a",
            "source": "Source A",
            "published": "",
            "time_ago": "recently",
            "timestamp": "",
        }
    ]
    html_text = RSSNewsProvider._format_news_response_html(articles, "query")
    assert "Title A" in html_text
    assert "http://example.com/a" in html_text
