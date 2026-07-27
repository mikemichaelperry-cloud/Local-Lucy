#!/usr/bin/env python3
"""Unified news provider entry point."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv

    _dotenv_available = True
except ImportError:
    _dotenv_available = False

from router_py.news.models import NewsResult
from router_py.news.rss import RSSNewsProvider

logger = logging.getLogger(__name__)


def _load_project_dotenv() -> None:
    """Load lucy-v11/.env so NEWSAPI_API_KEY is available."""
    if not _dotenv_available:
        return
    for root in (
        os.environ.get("LUCY_RUNTIME_AUTHORITY_ROOT"),
        os.environ.get("LUCY_ROOT"),
        str(Path(__file__).resolve().parent.parent.parent),
    ):
        if not root:
            continue
        env_path = Path(root).expanduser().resolve() / ".env"
        if env_path.exists():
            load_dotenv(env_path, override=False)
            break


_load_project_dotenv()


class NewsProvider:
    """
    Unified news provider that tries multiple sources.

    Usage:
        result = await NewsProvider.fetch_news("latest world news")
        if result.ok:
            print(result.text)
    """

    @classmethod
    async def fetch_news(cls, query: str = "", for_voice: bool = False) -> NewsResult:
        """
        Fetch news from RSS feeds (async, parallel, always fresh).

        Args:
            query: Search query (e.g., "world news", "technology", "sports")
            for_voice: If True, return condensed format optimized for TTS

        Returns:
            NewsResult with news articles
        """
        return await RSSNewsProvider.fetch_world_news_async(query, for_voice=for_voice)

    @classmethod
    def is_available(cls) -> bool:
        """Check if news fetching is available."""
        return True


# Convenience function for direct usage
def fetch_latest_news(query: str = "") -> str:
    """
    Fetch latest news and return formatted text.

    Args:
        query: Optional search query

    Returns:
        Formatted news text or error message
    """
    result = asyncio.run(NewsProvider.fetch_news(query))
    if result.ok:
        return result.text
    return f"Sorry, I couldn't fetch the news right now. {result.error}"
