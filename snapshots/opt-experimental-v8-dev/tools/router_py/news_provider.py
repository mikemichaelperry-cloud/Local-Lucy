#!/usr/bin/env python3
"""
News Provider - Fetches latest world news from RSS feeds and news APIs.

This module provides real-time news fetching for queries like "what's the latest world news".
It uses RSS feeds from reputable news sources (no API key required) and optionally
NewsAPI if an API key is available.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any


@dataclass(frozen=True)
class NewsResult:
    """Result from news fetching."""
    ok: bool
    text: str
    source: str
    error: str = ""
    articles: list[dict[str, Any]] | None = None


def _clean_html(text: str) -> str:
    """Remove HTML tags and entities."""
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    # Decode common HTML entities
    text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    text = text.replace('&quot;', '"').replace('&#39;', "'")
    text = text.replace('&nbsp;', ' ')
    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _format_time_ago(published: str) -> str:
    """Format publish time as 'X minutes/hours ago'."""
    try:
        # Normalize the published string - replace GMT with +0000
        normalized = published.strip()
        if normalized.endswith(" GMT"):
            normalized = normalized[:-4] + " +0000"
        elif normalized.endswith(" UTC"):
            normalized = normalized[:-4] + " +0000"
        
        # Try various date formats
        pub_time = None
        for fmt in [
            "%a, %d %b %Y %H:%M:%S %z",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%d %H:%M:%S",
        ]:
            try:
                pub_time = datetime.strptime(normalized, fmt)
                break
            except ValueError:
                continue
        
        if pub_time is None:
            return "recently"
        
        # Make timezone-aware comparison
        if pub_time.tzinfo:
            now = datetime.now(pub_time.tzinfo)
        else:
            # Assume UTC if no timezone
            from datetime import timezone
            pub_time = pub_time.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
        
        diff = now - pub_time
        
        if diff < timedelta(minutes=1):
            return "just now"
        elif diff < timedelta(hours=1):
            minutes = int(diff.seconds / 60)
            return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
        elif diff < timedelta(days=1):
            hours = int(diff.seconds / 3600)
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        else:
            days = diff.days
            return f"{days} day{'s' if days != 1 else ''} ago"
    except Exception:
        return "recently"


class RSSNewsProvider:
    """Fetch news from RSS feeds (no API key required)."""
    
    # Reputable world news RSS feeds (verified working with fresh content)
    RSS_FEEDS = {
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
    MAX_TOTAL_ARTICLES = 10
    
    # Region keywords to detect in queries
    REGION_KEYWORDS = {
        "middle_east": ["israel", "israeli", "jerusalem", "tel aviv", "palestine", "palestinian", 
                        "gaza", "hamas", "west bank", "lebanon", "hezbollah", "beirut",
                        "netanyahu", "idf", "iron dome", "middle east", "iran", "tehran",
                        "syria", "damascus", "yemen", "saudi", "saudi arabia", "qatar", 
                        "dubai", "uae", "baghdad", "iraq", "jordan", "amman", "egypt",
                        "cairo", "sinai", "ceasefire", "two-state solution", "settlement"],
        "australia": ["australia", "australian", "sydney", "melbourne", "canberra", "perth", 
                      "brisbane", "adelaide", "tasmania", "anzac", "aussie"],
    }
    
    @classmethod
    def fetch_world_news(cls, query: str = "") -> NewsResult:
        """
        Fetch latest world news from multiple RSS sources.
        
        Args:
            query: Optional search query to filter articles
            
        Returns:
            NewsResult with formatted news text
        """
        all_articles = []
        errors = []
        
        # Detect region from query
        query_lower = query.lower()
        detected_regions = set()
        for region, keywords in cls.REGION_KEYWORDS.items():
            if any(kw in query_lower for kw in keywords):
                detected_regions.add(region)
        
        # Prioritize feeds based on detected regions
        feeds_to_fetch = []
        for source_id, source_info in cls.RSS_FEEDS.items():
            feed_region = source_info.get("region", "world")
            # Include if it's a world feed or matches detected region
            if feed_region == "world" or feed_region in detected_regions:
                feeds_to_fetch.append((source_id, source_info))
        
        # Fetch from each selected source
        for source_id, source_info in feeds_to_fetch:
            try:
                articles = cls._fetch_rss_feed(
                    source_info["url"], 
                    source_info["name"],
                    query
                )
                all_articles.extend(articles[:cls.MAX_ARTICLES_PER_SOURCE])
            except Exception as e:
                errors.append(f"{source_info['name']}: {e}")
        
        if not all_articles:
            return NewsResult(
                ok=False,
                text="",
                source="rss",
                error=f"Failed to fetch news from all sources: {'; '.join(errors)}"
            )
        
        # Sort by time (most recent first) and limit
        all_articles.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        all_articles = all_articles[:cls.MAX_TOTAL_ARTICLES]
        
        # Format response with HTML for clickable links
        formatted = cls._format_news_response(all_articles, query, use_html=True)
        
        return NewsResult(
            ok=True,
            text=formatted,
            source="rss",
            articles=all_articles
        )
    
    @classmethod
    def _fetch_rss_feed(cls, url: str, source_name: str, query: str = "") -> list[dict[str, Any]]:
        """Fetch and parse an RSS feed."""
        articles = []
        
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Local Lucy News Fetcher)",
                "Accept": "application/rss+xml,application/xml,text/xml,*/*",
            },
            method="GET",
        )
        
        with urllib.request.urlopen(request, timeout=cls.TIMEOUT) as response:
            data = response.read().decode("utf-8", errors="replace")
        
        # Parse XML
        root = ET.fromstring(data)
        
        # Find items (handle both RSS 2.0 and Atom)
        channel = root.find("channel")
        if channel is not None:
            items = channel.findall("item")
        else:
            # Atom format
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            items = root.findall("atom:entry", ns)
        
        for item in items:
            # Extract title
            title_elem = item.find("title")
            title = _clean_html(title_elem.text) if title_elem is not None else ""
            
            # Extract description/summary
            desc_elem = item.find("description") or item.find("summary")
            if desc_elem is None:
                # Try Atom content
                desc_elem = item.find("{http://www.w3.org/2005/Atom}summary") or \
                           item.find("{http://www.w3.org/2005/Atom}content")
            description = _clean_html(desc_elem.text) if desc_elem is not None else ""
            
            # Extract link
            link_elem = item.find("link")
            if link_elem is not None:
                link = link_elem.text or link_elem.get("href", "")
            else:
                link = ""
            
            # Extract publish date
            # Note: Don't use 'or' with ElementTree - empty elements are falsy!
            pub_date_elem = item.find("pubDate")
            if pub_date_elem is None:
                pub_date_elem = item.find("published")
            if pub_date_elem is None:
                pub_date_elem = item.find("{http://www.w3.org/2005/Atom}published")
            pub_date = pub_date_elem.text if pub_date_elem is not None else ""
            
            # Normalize date for consistent parsing
            if pub_date:
                pub_date = pub_date.strip()
                if pub_date.endswith(" GMT"):
                    pub_date = pub_date[:-4] + " +0000"
                elif pub_date.endswith(" UTC"):
                    pub_date = pub_date[:-4] + " +0000"
            
            # Filter by query if provided (only for specific search terms)
            # Skip filtering for generic news queries
            generic_terms = ['latest', 'world news', 'news today', 'current news', 'breaking news']
            if query and not any(term in query.lower() for term in generic_terms):
                query_lower = query.lower()
                search_text = f"{title} {description}".lower()
                if query_lower not in search_text:
                    continue
            
            articles.append({
                "title": title,
                "description": description[:300] + "..." if len(description) > 300 else description,
                "url": link,
                "source": source_name,
                "published": pub_date,
                "time_ago": _format_time_ago(pub_date),
                "timestamp": pub_date,
            })
        
        return articles
    
    @classmethod
    def _format_news_response(cls, articles: list[dict[str, Any]], query: str = "", use_html: bool = False) -> str:
        """Format articles into readable text."""
        from datetime import datetime
        
        if use_html:
            return cls._format_news_response_html(articles, query)
        
        lines = []
        
        # Add fetch timestamp for verification
        fetch_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        if query:
            lines.append(f"Latest news about '{query}':")
        else:
            lines.append("Latest World News:")
        
        lines.append(f"(Fetched: {fetch_time})\n")
        
        for i, article in enumerate(articles, 1):
            lines.append(f"{i}. {article['title']}")
            lines.append(f"   Source: {article['source']} • {article['time_ago']}")
            if article['description']:
                lines.append(f"   {article['description']}")
            if article['url']:
                lines.append(f"   Read more: {article['url']}")
            lines.append("")
        
        return "\n".join(lines)
    
    @classmethod
    def _format_news_response_html(cls, articles: list[dict[str, Any]], query: str = "") -> str:
        """Format articles into HTML with clickable links."""
        from datetime import datetime
        import html
        
        lines = []
        
        # Add fetch timestamp for verification
        fetch_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        if query:
            lines.append(f"<p><b>Latest news about '{html.escape(query)}':</b></p>")
        else:
            lines.append("<p><b>Latest World News:</b></p>")
        
        lines.append(f'<p style="color: #666; font-size: 0.9em;">(Fetched: {fetch_time})</p>')
        lines.append("")
        
        for i, article in enumerate(articles, 1):
            title = html.escape(article['title'])
            source = html.escape(article['source'])
            time_ago = html.escape(article['time_ago'])
            description = html.escape(article['description']) if article['description'] else ""
            url = article['url']
            
            lines.append(f'<p><b>{i}. {title}</b><br>')
            lines.append(f'   <span style="color: #666;">Source: {source} • {time_ago}</span><br>')
            
            if description:
                lines.append(f'   {description}<br>')
            
            if url:
                # Create clickable link
                safe_url = html.escape(url)
                lines.append(f'   <a href="{safe_url}" style="color: #0066cc; text-decoration: underline;">Read more</a>')
            
            lines.append('</p>')
        
        return "\n".join(lines)


class NewsAPIProvider:
    """Fetch news from NewsAPI (requires API key)."""
    
    DEFAULT_API_BASE = "https://newsapi.org/v2"
    TIMEOUT = 15.0
    MAX_ARTICLES = 10
    
    @classmethod
    def fetch_world_news(cls, query: str = "", api_key: str = "") -> NewsResult:
        """
        Fetch latest world news from NewsAPI.
        
        Args:
            query: Optional search query
            api_key: NewsAPI key (or from NEWSAPI_API_KEY env var)
            
        Returns:
            NewsResult with formatted news text
        """
        api_key = api_key or os.environ.get("NEWSAPI_API_KEY", "").strip()
        if not api_key:
            return NewsResult(
                ok=False,
                text="",
                source="newsapi",
                error="NewsAPI key not configured (set NEWSAPI_API_KEY environment variable)"
            )
        
        # Build request URL
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
                ok=False,
                text="",
                source="newsapi",
                error=f"NewsAPI HTTP error: {e.code}"
            )
        except Exception as e:
            return NewsResult(
                ok=False,
                text="",
                source="newsapi",
                error=f"NewsAPI request failed: {e}"
            )
        
        if data.get("status") != "ok":
            return NewsResult(
                ok=False,
                text="",
                source="newsapi",
                error=f"NewsAPI error: {data.get('message', 'Unknown error')}"
            )
        
        articles = data.get("articles", [])
        if not articles:
            return NewsResult(
                ok=False,
                text="",
                source="newsapi",
                error="No articles found"
            )
        
        # Format articles
        formatted_articles = []
        for article in articles:
            pub_date = article.get("publishedAt", "")
            formatted_articles.append({
                "title": article.get("title", ""),
                "description": article.get("description", ""),
                "url": article.get("url", ""),
                "source": article.get("source", {}).get("name", "Unknown"),
                "published": pub_date,
                "time_ago": _format_time_ago(pub_date),
                "timestamp": pub_date,
            })
        
        formatted = RSSNewsProvider._format_news_response(formatted_articles, query, use_html=True)
        
        return NewsResult(
            ok=True,
            text=formatted,
            source="newsapi",
            articles=formatted_articles
        )


class NewsProvider:
    """
    Unified news provider that tries multiple sources.
    
    Usage:
        result = NewsProvider.fetch_news("latest world news")
        if result.ok:
            print(result.text)
    """
    
    @classmethod
    def fetch_news(cls, query: str = "") -> NewsResult:
        """
        Fetch news using best available source.
        
        Priority:
        1. NewsAPI (if API key configured)
        2. RSS feeds (no API key needed)
        
        Args:
            query: Search query (e.g., "world news", "technology", "sports")
            
        Returns:
            NewsResult with news articles
        """
        # Try NewsAPI first if key is available
        if os.environ.get("NEWSAPI_API_KEY"):
            result = NewsAPIProvider.fetch_world_news(query)
            if result.ok:
                return result
        
        # Fallback to RSS feeds
        return RSSNewsProvider.fetch_world_news(query)
    
    @classmethod
    def is_available(cls) -> bool:
        """Check if news fetching is available."""
        # RSS feeds are always available (unless network is down)
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
    result = NewsProvider.fetch_news(query)
    if result.ok:
        return result.text
    return f"Sorry, I couldn't fetch the news right now. {result.error}"


if __name__ == "__main__":
    # Test the news provider
    print("Fetching latest world news...\n")
    print(fetch_latest_news())
