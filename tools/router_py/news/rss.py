#!/usr/bin/env python3
"""RSS news provider."""

from __future__ import annotations

import asyncio
import difflib
import html
import json
import logging
import os
import re
import string
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import aiohttp

from router_py.news.models import NewsResult
from router_py.news.utils import (
    _article_is_stale,
    _clean_html,
    _detect_source_disagreement,
    _format_time_ago,
    _parse_rfc822_date,
    _query_asks_for_history,
)

logger = logging.getLogger(__name__)


class RSSNewsProvider:
    """Fetch news from RSS feeds (no API key required)."""

    # Reputable world news RSS feeds (verified working with fresh content)
    RSS_FEEDS = {
        # World
        "bbc_world": {
            "url": "http://feeds.bbci.co.uk/news/world/rss.xml",
            "name": "BBC World News",
            "region": "world",
        },
        "guardian_world": {
            "url": "https://www.theguardian.com/world/rss",
            "name": "The Guardian",
            "region": "world",
        },
        "nyt_world": {
            "url": "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
            "name": "New York Times World",
            "region": "world",
        },
        "npr_news": {
            "url": "https://feeds.npr.org/1001/rss.xml",
            "name": "NPR News",
            "region": "world",
        },
        "reuters_world": {
            "url": "https://www.reutersagency.com/feed/?best-topics=world-news",
            "name": "Reuters World",
            "region": "world",
        },
        "al_jazeera": {
            "url": "https://www.aljazeera.com/xml/rss/all.xml",
            "name": "Al Jazeera",
            "region": "world",
        },
        "cnn_world": {
            "url": "http://rss.cnn.com/rss/edition_world.rss",
            "name": "CNN World",
            "region": "world",
        },
        "dw_world": {
            "url": "https://rss.dw.com/rdf/rss-en-world",
            "name": "DW World",
            "region": "world",
        },
        "france24": {
            "url": "https://www.france24.com/en/rss",
            "name": "France 24",
            "region": "world",
        },
        # Middle East / Israel
        "bbc_middle_east": {
            "url": "http://feeds.bbci.co.uk/news/world/middle_east/rss.xml",
            "name": "BBC Middle East",
            "region": "middle_east",
        },
        "times_of_israel": {
            "url": "https://www.timesofisrael.com/feed/",
            "name": "Times of Israel",
            "region": "middle_east",
        },
        "israel_hayom": {
            "url": "https://www.israelhayom.com/feed/",
            "name": "Israel Hayom",
            "region": "middle_east",
        },
        "jerusalem_post": {
            "url": "https://www.jpost.com/rss/",
            "name": "Jerusalem Post",
            "region": "middle_east",
        },
        "haaretz": {
            "url": "https://www.haaretz.com/rss-feeds/1.147",
            "name": "Haaretz",
            "region": "middle_east",
        },
        "ynetnews": {
            "url": "https://www.ynetnews.com/category/3089/rss",
            "name": "Ynetnews",
            "region": "middle_east",
        },
        "i24news": {
            "url": "https://www.i24news.tv/en/rss",
            "name": "i24NEWS",
            "region": "middle_east",
        },
        # Australia
        "guardian_australia": {
            "url": "https://www.theguardian.com/australia-news/rss",
            "name": "The Guardian Australia",
            "region": "australia",
        },
        "abc_australia": {
            "url": "https://www.abc.net.au/news/feed/2942460/rss.xml",
            "name": "ABC News Australia",
            "region": "australia",
        },
        "abc_aus_politics": {
            "url": "https://www.abc.net.au/news/feed/1534/rss.xml",
            "name": "ABC News Australia Politics",
            "region": "australia",
        },
        "news_com_au": {
            "url": "https://www.news.com.au/content-feeds/latest-news-national/",
            "name": "News.com.au",
            "region": "australia",
        },
        "smh": {
            "url": "https://www.smh.com.au/rss/feed.xml",
            "name": "Sydney Morning Herald",
            "region": "australia",
        },
        "the_age": {
            "url": "https://www.theage.com.au/rss/feed.xml",
            "name": "The Age",
            "region": "australia",
        },
        "crikey": {
            "url": "https://www.crikey.com.au/feed/",
            "name": "Crikey",
            "region": "australia",
        },
    }

    TIMEOUT = 10.0
    MAX_ARTICLES_PER_SOURCE = 3
    MAX_TOTAL_ARTICLES = 15
    # Region keywords to detect in queries
    REGION_KEYWORDS = {
        "middle_east": [
            "israel",
            "israeli",
            "israel's",
            "jerusalem",
            "tel aviv",
            "haifa",
            "palestine",
            "palestinian",
            "palestinians",
            "gaza",
            "gazan",
            "hamas",
            "west bank",
            "lebanon",
            "lebanese",
            "hezbollah",
            "beirut",
            "netanyahu",
            "idf",
            "iron dome",
            "middle east",
            "mideast",
            "iran",
            "iranian",
            "tehran",
            "syria",
            "damascus",
            "yemen",
            "saudi",
            "saudi arabia",
            "qatar",
            "doha",
            "uae",
            "dubai",
            "abudhabi",
            "baghdad",
            "iraq",
            "jordan",
            "amman",
            "egypt",
            "cairo",
            "sinai",
            "ceasefire",
            "two-state solution",
            "settlement",
            "zionist",
            "zionism",
            "knesset",
            "al-aqsa",
            "dome of the rock",
            "golan heights",
        ],
        "australia": [
            "australia",
            "australian",
            "aussie",
            "auspol",
            "sydney",
            "melbourne",
            "canberra",
            "perth",
            "brisbane",
            "adelaide",
            "tasmania",
            "hobart",
            "darwin",
            "gold coast",
            "newcastle",
            "wollongong",
            "anzac",
            "anzus",
            "scott morrison",
            "anthony albanese",
            "albo",
            "liberal party",
            "labor party",
            "coles",
            "woolworths",
            "qantas",
        ],
    }

    @classmethod
    def _filter_by_recency(
        cls, articles: list[dict[str, Any]], query: str, days: int = 7
    ) -> list[dict[str, Any]]:
        """Drop articles older than *days* days unless the query asks for history."""
        if _query_asks_for_history(query):
            return articles
        return [
            article
            for article in articles
            if not _article_is_stale(article.get("published", ""), days=days)
        ]

    @classmethod
    def _detect_region(cls, query: str) -> set[str]:
        """Detect regions from query keywords, including common misspellings."""
        query_lower = query.lower()
        detected = set()
        for region, keywords in cls.REGION_KEYWORDS.items():
            if any(kw in query_lower for kw in keywords):
                detected.add(region)
                continue
            # Fuzzy fallback for typos (e.g. "Iraeli" -> "Israeli").
            tokens = re.findall(r"[a-zA-Z']+", query_lower)
            for keyword in keywords:
                if keyword in query_lower:
                    detected.add(region)
                    break
                if len(keyword) >= 5:
                    for token in tokens:
                        if (
                            len(token) >= 4
                            and difflib.SequenceMatcher(None, token, keyword).ratio() >= 0.80
                        ):
                            detected.add(region)
                            break
                    if region in detected:
                        break
        return detected

    @classmethod
    def _get_feeds_for_query(cls, query: str) -> list[tuple[str, dict[str, str]]]:
        """Return ordered list of (feed_id, feed_info) tuples for a query."""
        detected_regions = cls._detect_region(query)
        regional_feeds = []
        world_feeds = []

        for source_id, source_info in cls.RSS_FEEDS.items():
            feed_region = source_info.get("region", "world")
            if feed_region in detected_regions:
                regional_feeds.append((source_id, source_info))
            elif feed_region == "world":
                world_feeds.append((source_id, source_info))

        if detected_regions:
            return regional_feeds + world_feeds
        return world_feeds

    @classmethod
    async def _fetch_rss_feed_async(
        cls,
        session: aiohttp.ClientSession,
        source_id: str,
        source_info: dict[str, str],
        query: str = "",
    ) -> list[dict[str, Any]]:
        """Fetch and parse a single RSS feed asynchronously."""
        url = source_info["url"]
        source_name = source_info["name"]
        articles = []

        try:
            async with session.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Local Lucy News Fetcher)",
                    "Accept": "application/rss+xml,application/xml,text/xml,*/*",
                    "Cache-Control": "no-cache",
                    "Pragma": "no-cache",
                },
                timeout=aiohttp.ClientTimeout(total=cls.TIMEOUT),
            ) as response:
                data = await response.read()
        except Exception:
            # Let the caller decide how to handle
            raise

        # Hardened XML parsing: cap size
        text = data.decode("utf-8", errors="replace")
        if len(text) > 2_000_000:
            raise ValueError("Feed response too large (>2MB)")

        root = ET.fromstring(text)

        # Find items (handle both RSS 2.0 and Atom)
        channel = root.find("channel")
        if channel is not None:
            items = channel.findall("item")
        else:
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            items = root.findall("atom:entry", ns)

        # Pre-parse a channel-level fallback timestamp for feeds that omit
        # item-level pubDate (e.g. news.com.au).
        channel_fallback_dt: datetime | None = None
        if channel is not None:
            for fallback_tag in ("lastBuildDate", "pubDate"):
                fb_elem = channel.find(fallback_tag)
                if fb_elem is not None and fb_elem.text:
                    channel_fallback_dt = _parse_rfc822_date(fb_elem.text)
                    break

        for idx, item in enumerate(items):
            title_elem = item.find("title")
            title = _clean_html(title_elem.text) if title_elem is not None else ""

            desc_elem = item.find("description")
            if desc_elem is None:
                desc_elem = item.find("summary")
            if desc_elem is None:
                desc_elem = item.find("{http://www.w3.org/2005/Atom}summary")
            if desc_elem is None:
                desc_elem = item.find("{http://www.w3.org/2005/Atom}content")
            description = _clean_html(desc_elem.text) if desc_elem is not None else ""

            link_elem = item.find("link")
            if link_elem is not None:
                link = link_elem.text or link_elem.get("href", "")
            else:
                link = ""

            pub_date_elem = item.find("pubDate")
            if pub_date_elem is None:
                pub_date_elem = item.find("published")
            if pub_date_elem is None:
                pub_date_elem = item.find("{http://www.w3.org/2005/Atom}published")
            pub_date = pub_date_elem.text if pub_date_elem is not None else ""

            has_own_date = bool(pub_date)
            if pub_date:
                pub_date = pub_date.strip()
                if pub_date.endswith(" GMT"):
                    pub_date = pub_date[:-4] + " +0000"
                elif pub_date.endswith(" UTC"):
                    pub_date = pub_date[:-4] + " +0000"
            elif channel_fallback_dt is not None:
                # Feeds without per-item timestamps: stagger slightly by position
                # so the first item is considered newest, second slightly older, etc.
                staggered = channel_fallback_dt - timedelta(seconds=idx)
                pub_date = staggered.strftime("%a, %d %b %Y %H:%M:%S %z")

            # Filter by query if provided (only for specific search terms)
            generic_terms = [
                "latest",
                "world news",
                "news today",
                "current news",
                "breaking news",
                "news",
                "headlines",
                "headline",
                "todays",
                "today's",
            ]
            if query and not any(term in query.lower() for term in generic_terms):
                query_lower = query.lower()
                search_text = f"{title} {description}".lower()
                import string

                # Strip punctuation from keywords to avoid "headlines?" not matching "headlines"
                stopwords = {
                    "what",
                    "when",
                    "where",
                    "which",
                    "latest",
                    "current",
                    "about",
                    "are",
                    "the",
                    "for",
                    "any",
                }
                keywords = []
                for w in query_lower.split():
                    w_clean = w.strip(string.punctuation)
                    if len(w_clean) > 3 and w_clean not in stopwords:
                        keywords.append(w_clean)
                if keywords and not any(kw in search_text for kw in keywords):
                    continue

            # Truncate description to 2-3 sentences (~400 chars) for clean display
            clean_desc = description.strip()
            if len(clean_desc) > 400:
                # Try to break at sentence boundary
                sentence_end = clean_desc.find(". ", 150, 400)
                if sentence_end == -1:
                    sentence_end = clean_desc.rfind(" ", 350, 400)
                if sentence_end == -1:
                    sentence_end = 380
                clean_desc = clean_desc[:sentence_end].rstrip() + "."

            sort_dt = _parse_rfc822_date(pub_date)
            articles.append(
                {
                    "title": title,
                    "description": clean_desc,
                    "url": link,
                    "source": source_name,
                    "published": pub_date,
                    "time_ago": _format_time_ago(pub_date),
                    "timestamp": pub_date,
                    "_sort_dt": sort_dt,
                }
            )

        return articles

    @classmethod
    async def fetch_world_news_async(cls, query: str = "", for_voice: bool = False) -> NewsResult:
        """
        Fetch latest world news from multiple RSS sources asynchronously.

        Uses parallel aiohttp fetching and always fetches fresh results.
        Returns partial results if some feeds fail.
        """
        # NOTE: News is always fetched fresh — no caching.
        # Queries like "latest news" explicitly request current content.
        # Parallel aiohttp fetching makes this fast enough (~2-6s) that
        # cache hits are not worth stale headlines.

        feeds = cls._get_feeds_for_query(query)
        if not feeds:
            return NewsResult(
                ok=False,
                text="",
                source="rss",
                error="No RSS feeds configured for this query.",
            )

        all_articles: list[dict[str, Any]] = []
        errors: list[str] = []

        connector = aiohttp.TCPConnector(limit=20, limit_per_host=4, ttl_dns_cache=300)
        fetch_start = time.time()
        async with aiohttp.ClientSession(connector=connector) as session:
            tasks = []
            for source_id, source_info in feeds:
                tasks.append(cls._fetch_rss_feed_async(session, source_id, source_info, query))

            results = await asyncio.gather(*tasks, return_exceptions=True)

            for (source_id, source_info), result in zip(feeds, results):
                if isinstance(result, Exception):
                    errors.append(f"{source_info['name']}: {type(result).__name__}")
                    continue
                # Apply per-source limits based on region priority
                feed_region = source_info.get("region", "world")
                detected = cls._detect_region(query)
                if detected and feed_region in detected:
                    all_articles.extend(result[: cls.MAX_ARTICLES_PER_SOURCE + 2])
                elif detected and feed_region == "world":
                    all_articles.extend(result[:1])
                else:
                    all_articles.extend(result[: cls.MAX_ARTICLES_PER_SOURCE])

            # Fallback to web search when RSS yields nothing, improving reliability
            # for breaking or niche topics not yet in feeds.
            if not all_articles and query:
                search_articles = await cls._fetch_news_via_search(query, session)
                if search_articles:
                    all_articles.extend(search_articles)
                    errors.append("rss_empty_used_web_search_fallback")

        logger.info(
            f"NEWS fetch completed in {(time.time() - fetch_start):.2f}s for query: {query!r}"
        )

        if not all_articles:
            return NewsResult(
                ok=False,
                text="",
                source="rss",
                error=f"Failed to fetch news from all sources. Errors: {'; '.join(errors)}",
            )

        # Deduplicate by normalized title
        seen_titles: set[str] = set()
        deduped: list[dict[str, Any]] = []
        for article in all_articles:
            norm = article.get("title", "").strip().lower().rstrip(".…!?:;")
            if norm and norm not in seen_titles:
                seen_titles.add(norm)
                deduped.append(article)
        all_articles = deduped

        # Recency scoring: drop articles older than 7 days unless the query
        # explicitly asks for historical news. This prevents stale headlines
        # from ranking highly for "latest news" queries.
        all_articles = cls._filter_by_recency(all_articles, query)

        # Sort by parsed datetime (most recent first).  Feeds without parseable
        # timestamps sort to the end so they don't push fresher content down.
        all_articles.sort(
            key=lambda x: (x.get("_sort_dt") is not None, x.get("_sort_dt")),
            reverse=True,
        )

        # Enforce a per-source cap so one fast-updating feed can't monopolise
        # the top 10 slots.
        source_counts: dict[str, int] = {}
        capped: list[dict[str, Any]] = []
        for article in all_articles:
            src = article.get("source", "")
            if source_counts.get(src, 0) < cls.MAX_ARTICLES_PER_SOURCE:
                source_counts[src] = source_counts.get(src, 0) + 1
                capped.append(article)
            if len(capped) >= cls.MAX_TOTAL_ARTICLES:
                break
        all_articles = capped

        # Source cross-check: when multiple feeds are available, detect
        # conflicting claims among the top items from different sources.
        disagreement = _detect_source_disagreement(all_articles[: cls.MAX_TOTAL_ARTICLES])

        # Format response
        formatted = cls._format_news_response(all_articles, query, for_voice=for_voice)
        html_formatted = cls._format_news_response(
            all_articles, query, use_html=True, for_voice=for_voice
        )

        return NewsResult(
            ok=True,
            text=formatted,
            source="rss",
            articles=all_articles,
            partial=bool(errors),
            errors=errors if errors else None,
            html_text=html_formatted,
            disagreement=disagreement,
        )

    @classmethod
    def fetch_world_news(cls, query: str = "", for_voice: bool = False) -> NewsResult:
        """
        Synchronous wrapper around async fetch.

        For use from non-async contexts. Prefer fetch_world_news_async in async code.
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # We're inside an async context but being called sync — schedule it
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(
                        asyncio.run, cls.fetch_world_news_async(query, for_voice=for_voice)
                    )
                    return future.result(timeout=60)
            else:
                return loop.run_until_complete(
                    cls.fetch_world_news_async(query, for_voice=for_voice)
                )
        except RuntimeError:
            # No event loop
            return asyncio.run(cls.fetch_world_news_async(query, for_voice=for_voice))

    @classmethod
    def _format_news_response(
        cls,
        articles: list[dict[str, Any]],
        query: str = "",
        use_html: bool = False,
        for_voice: bool = False,
    ) -> str:
        """Format articles into readable text or HTML.

        Args:
            articles: List of article dictionaries
            query: Optional search query
            use_html: If True, return HTML formatted text with clickable links
            for_voice: If True, return condensed natural format for TTS
        """
        # HTML and voice are independent display formats.
        # Check HTML first so callers can request both formats in one call.
        if use_html:
            return cls._format_news_response_html(articles, query)
        if for_voice:
            return cls._format_news_response_voice(articles, query)
        # Default: return plain text (URLs will be auto-linked by conversation panel)
        return cls._format_news_response_plain(articles, query)

    @classmethod
    def _format_news_response_plain(cls, articles: list[dict[str, Any]], query: str = "") -> str:
        """Plain text format: numbered headlines, short info, source/timestamp, Read more URL."""
        lines = []
        fetch_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if query:
            lines.append(f"Latest news about '{query}':")
        else:
            lines.append("Latest World News:")
        lines.append(f"(Fetched: {fetch_time})\n")

        for i, article in enumerate(articles, 1):
            lines.append(f"{i}. {article['title']}")
            if article.get("description"):
                lines.append(f"   {article['description']}")
            lines.append(f"   {article['source']} • {article['time_ago']}")
            if article.get("url"):
                lines.append(f"   Read more: {article['url']}")
            lines.append("")

        return "\n".join(lines)

    @classmethod
    def _format_news_response_voice(cls, articles: list[dict[str, Any]], query: str = "") -> str:
        """Natural, concise voice format for Kokoro TTS.

        Reads as: "Headline, from Source. Brief info. Next: Headline, from Source."
        """
        if not articles:
            return "No news available at the moment."

        parts = []
        # Optional brief intro for voice (omitted to keep it snappy)
        for i, article in enumerate(articles):
            title = article.get("title", "")
            source = article.get("source", "")
            desc = article.get("description", "")

            line = f"{title}, from {source}."
            if desc and len(desc) > 20:
                # Append brief description if meaningful
                line += f" {desc}"
            parts.append(line)

        return " ".join(parts)

    @classmethod
    def _format_news_response_html(cls, articles: list[dict[str, Any]], query: str = "") -> str:
        """HTML format with clickable Read more links for PySide6 QTextBrowser."""
        fetch_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        parts: list[str] = []

        header = f"Latest news about '{query}':" if query else "Latest World News:"
        parts.append(f'<p style="margin: 4px 0;"><b>{html.escape(header)}</b></p>')
        parts.append(
            f'<p style="margin: 4px 0; color: #888; font-size: 0.85em;">(Fetched: {html.escape(fetch_time)})</p>'
        )

        for i, article in enumerate(articles, 1):
            title = html.escape(article.get("title", ""))
            source = html.escape(article.get("source", ""))
            time_ago = html.escape(article.get("time_ago", ""))
            description = html.escape(article.get("description", ""))
            url = article.get("url", "")

            parts.append(
                '<div style="margin: 10px 0; padding: 6px 0; border-bottom: 1px solid #3a4a5a;">'
            )
            parts.append(f'<p style="margin: 2px 0; font-size: 14px;"><b>{i}. {title}</b></p>')
            parts.append(
                f'<p style="margin: 2px 0; color: #888; font-size: 0.85em;">Source: {source} • {time_ago}</p>'
            )
            if description:
                parts.append(f'<p style="margin: 2px 0; color: #c8d0d6;">{description}</p>')
            if url:
                safe_url = html.escape(url)
                parts.append(
                    f'<p style="margin: 2px 0;">'
                    f'<a href="{safe_url}" style="color: #66b3ff; text-decoration: underline;">Read more</a>'
                    f"</p>"
                )
            parts.append("</div>")

        body = "\n".join(parts)
        return (
            '<html><body style="font-family: sans-serif; font-size: 13px; color: #d8e0e6;">'
            f"{body}"
            "</body></html>"
        )

    @classmethod
    async def _fetch_news_via_search(
        cls, query: str, session: aiohttp.ClientSession
    ) -> list[dict[str, Any]]:
        """Fallback news fetch using the project's web-search tool.

        This is used when RSS feeds fail or return no relevant articles. It
        broadens coverage and improves reliability for niche or breaking topics.
        """
        search_script = Path(__file__).resolve().parents[3] / "tools" / "internet" / "search_web.py"
        if not search_script.exists():
            return []

        # Append "news" to focus search results on current events.
        search_query = f"{query} news".strip()
        try:
            payload = json.dumps({"query": search_query, "max_results": 10})
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                str(search_script),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(search_script.parent.parent.parent),
                env={**os.environ, "PYTHONPATH": str(search_script.parent.parent.parent)},
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(payload.encode("utf-8")), timeout=20.0
            )
            if proc.returncode != 0:
                logger.warning(f"News web-search fallback failed: {stderr.decode()[:200]}")
                return []
            data = json.loads(stdout.decode("utf-8"))
            results = data.get("results", [])
            articles = []
            for item in results:
                title = item.get("title", "").strip()
                snippet = item.get("snippet", "").strip()
                url = item.get("url", "").strip()
                if not title:
                    continue
                if len(snippet) > 400:
                    sentence_end = snippet.find(". ", 150, 400)
                    if sentence_end == -1:
                        sentence_end = snippet.rfind(" ", 350, 400)
                    if sentence_end == -1:
                        sentence_end = 380
                    snippet = snippet[:sentence_end].rstrip() + "."
                articles.append(
                    {
                        "title": title,
                        "description": snippet,
                        "url": url,
                        "source": item.get("source", "web search"),
                        "published": "",
                        "time_ago": "recently",
                        "timestamp": "",
                        "_sort_dt": None,
                    }
                )
            return articles
        except Exception as e:
            logger.warning(f"News web-search fallback error: {e}")
            return []
