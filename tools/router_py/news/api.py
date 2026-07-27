#!/usr/bin/env python3
"""NewsAPI news provider."""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from router_py.news.models import NewsResult
from router_py.news.provider import _load_project_dotenv
from router_py.news.rss import RSSNewsProvider
from router_py.news.utils import _format_time_ago

logger = logging.getLogger(__name__)

_load_project_dotenv()


class NewsAPIProvider:
    """Fetch news from NewsAPI (requires API key)."""

    DEFAULT_API_BASE = "https://newsapi.org/v2"
    TIMEOUT = 15.0
    MAX_ARTICLES = 10

    @classmethod
    def fetch_world_news(
        cls, query: str = "", api_key: str = "", for_voice: bool = False
    ) -> NewsResult:
        """
        Fetch latest world news from NewsAPI.

        Args:
            query: Optional search query
            api_key: NewsAPI key (or from NEWSAPI_API_KEY env var)
            for_voice: If True, return condensed format optimized for TTS

        Returns:
            NewsResult with news articles
        """
        api_key = api_key or os.environ.get("NEWSAPI_API_KEY", "").strip()
        if not api_key:
            return NewsResult(
                ok=False,
                text="",
                source="newsapi",
                error="NewsAPI key not configured: set NEWSAPI_API_KEY in lucy-v11/.env or environment",
            )

        if query:
            endpoint = f"{cls.DEFAULT_API_BASE}/everything"
            params = f"?q={urllib.parse.quote(query)}&sortBy=publishedAt&language=en&pageSize={cls.MAX_ARTICLES}"
        else:
            endpoint = f"{cls.DEFAULT_API_BASE}/top-headlines"
            params = f"?category=general&language=en&pageSize={cls.MAX_ARTICLES}"

        url = f"{endpoint}{params}&apiKey={api_key}"

        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Local Lucy News Fetcher",
                "Accept": "application/json",
            },
            method="GET",
        )

        try:
            with urllib.request.urlopen(request, timeout=cls.TIMEOUT) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return NewsResult(
                ok=False, text="", source="newsapi", error=f"NewsAPI HTTP error: {e.code}"
            )
        except Exception as e:
            return NewsResult(
                ok=False, text="", source="newsapi", error=f"NewsAPI request failed: {e}"
            )

        if data.get("status") != "ok":
            return NewsResult(
                ok=False,
                text="",
                source="newsapi",
                error=f"NewsAPI error: {data.get('message', 'Unknown error')}",
            )

        articles = data.get("articles", [])
        if not articles:
            return NewsResult(ok=False, text="", source="newsapi", error="No articles found")

        formatted_articles = []
        for article in articles:
            pub_date = article.get("publishedAt", "")
            desc = article.get("description", "") or ""
            if len(desc) > 400:
                sentence_end = desc.find(". ", 150, 400)
                if sentence_end == -1:
                    sentence_end = desc.rfind(" ", 350, 400)
                if sentence_end == -1:
                    sentence_end = 380
                desc = desc[:sentence_end].rstrip() + "."

            formatted_articles.append(
                {
                    "title": article.get("title", ""),
                    "description": desc,
                    "url": article.get("url", ""),
                    "source": article.get("source", {}).get("name", "Unknown"),
                    "published": pub_date,
                    "time_ago": _format_time_ago(pub_date),
                    "timestamp": pub_date,
                }
            )

        formatted = RSSNewsProvider._format_news_response(
            formatted_articles, query, use_html=False, for_voice=for_voice
        )
        html_formatted = RSSNewsProvider._format_news_response(
            formatted_articles, query, use_html=True, for_voice=for_voice
        )

        return NewsResult(
            ok=True,
            text=formatted,
            source="newsapi",
            articles=formatted_articles,
            html_text=html_formatted,
        )
