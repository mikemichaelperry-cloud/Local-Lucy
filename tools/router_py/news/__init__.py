#!/usr/bin/env python3
"""Local Lucy news fetching package."""

from router_py.news.models import NewsResult
from router_py.news.provider import NewsProvider, fetch_latest_news
from router_py.news.rss import RSSNewsProvider
from router_py.news.api import NewsAPIProvider

__all__ = [
    "NewsResult",
    "NewsProvider",
    "fetch_latest_news",
    "RSSNewsProvider",
    "NewsAPIProvider",
]
