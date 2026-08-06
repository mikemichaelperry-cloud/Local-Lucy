#!/usr/bin/env python3
"""General-knowledge web fetcher behind the ``auto_web_general_knowledge`` flag.

Fetches DuckDuckGo HTML results and returns the first matching result. All
results are explicitly labelled ``web_untrusted``; the pipeline never replaces
a local answer with fetched content.
"""

from __future__ import annotations

import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any

from router_py.escalation.critical_guard import is_critical_category
from router_py.request_types import ClassificationResult

logger = logging.getLogger(__name__)

_DUCKDUCKGO_HTML_URL = "https://html.duckduckgo.com/html/"


@dataclass(frozen=True)
class FetchResult:
    """A single untrusted web result for attribution/escalation."""

    url: str
    title: str
    snippet: str
    source_type: str = "web_untrusted"


class _DuckDuckGoResultParser(HTMLParser):
    """Parse DuckDuckGo HTML result pages into structured records."""

    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._current: dict[str, Any] | None = None
        self._capture_target: str | None = None
        self._text_buffer: list[str] = []

    def _flush_text(self) -> str:
        text = "".join(self._text_buffer).strip()
        self._text_buffer = []
        return " ".join(text.split())

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = {k: (v or "") for k, v in attrs}
        classes = attr_dict.get("class", "")

        if tag == "a" and "result__a" in classes:
            self._current = {"title": "", "url": "", "snippet": "", "_title_done": False}
            self._capture_target = "title"
            self._current["url"] = _decode_ddg_url(attr_dict.get("href", ""))
            return

        if self._current is None:
            return

        if tag == "a" and "result__snippet" in classes:
            self._capture_target = "snippet"
            return

        if tag == "a" and "result__url" in classes:
            # Prefer the clean result URL (href) when available.
            clean_url = attr_dict.get("href", "")
            if clean_url and self._current is not None:
                self._current["url"] = _normalise_url(clean_url)
            return

    def handle_endtag(self, tag: str) -> None:
        if self._current is None:
            return

        if self._capture_target == "title" and tag == "a":
            self._current["title"] = self._flush_text()
            self._current["_title_done"] = True
            self._capture_target = None
            return

        if self._capture_target == "snippet" and tag == "a":
            self._current["snippet"] = self._flush_text()
            self._capture_target = None
            return

        if tag == "div" and self._current.get("_title_done"):
            # End of a result block: save and reset.
            self.results.append(
                {
                    "title": self._current.get("title", ""),
                    "url": self._current.get("url", ""),
                    "snippet": self._current.get("snippet", ""),
                }
            )
            self._current = None

    def handle_data(self, data: str) -> None:
        if self._capture_target is not None:
            self._text_buffer.append(data)


def _decode_ddg_url(href: str) -> str:
    """Extract the real URL from a DuckDuckGo redirect link."""
    if not href:
        return ""
    # Some DDG links are protocol-relative.
    if href.startswith("//"):
        href = "https:" + href
    parsed = urllib.parse.urlparse(href)
    query = urllib.parse.parse_qs(parsed.query)
    if "uddg" in query:
        return query["uddg"][0]
    # Fallback: return the href itself if it is already a real URL.
    return _normalise_url(href)


def _normalise_url(url: str) -> str:
    """Ensure the URL has a scheme and no trailing slash noise."""
    url = url.strip()
    if url.startswith("//"):
        url = "https:" + url
    if not urllib.parse.urlparse(url).scheme:
        url = "https://" + url
    return url


def _domain_for(url: str) -> str:
    """Return the lower-cased registered domain-ish part of *url*."""
    parsed = urllib.parse.urlparse(url)
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc


def _matches_allowed_domains(url: str, allowed_domains: list[str]) -> bool:
    """Return True when *url*'s domain matches one of *allowed_domains*."""
    if not allowed_domains:
        return True
    target = _domain_for(url)
    for allowed in allowed_domains:
        allowed = allowed.lower().strip()
        if not allowed:
            continue
        if target == allowed or target.endswith("." + allowed):
            return True
    return False


# Known misinformation / conspiracy / hoax domains. These are dropped from
# DuckDuckGo fallback results so the engine does not amplify them.
_KNOWN_MISINFORMATION_DOMAINS = frozenset(
    {
        "naturalnews.com",
        "beforeitsnews.com",
        "infowars.com",
        "prisonplanet.com",
        "globalresearch.ca",
        "activistpost.com",
        "stillnessinthestorm.com",
        "yournewswire.com",
        "christiantruther.com",
    }
)


def _is_misinformation_domain(url: str) -> bool:
    """Return True when *url* is on the known misinformation blocklist."""
    return _domain_for(url) in _KNOWN_MISINFORMATION_DOMAINS


def _build_search_url(query: str) -> str:
    """Build a DuckDuckGo HTML search URL for *query*."""
    params = urllib.parse.urlencode({"q": query})
    return f"{_DUCKDUCKGO_HTML_URL}?{params}"


def fetch_general_knowledge(
    query: str,
    allowed_domains: list[str] | None = None,
    *,
    classification: ClassificationResult | None = None,
) -> FetchResult:
    """Fetch the first DuckDuckGo HTML result for *query*.

    Args:
        query: The search query (typically the user's question).
        allowed_domains: Optional list of domains to restrict results to.
            When provided, only results whose URL matches one of these
            domains are returned. Subdomains are accepted.
        classification: Optional classification for defense-in-depth
            critical-category blocking. When provided and the category is
            critical, the fetch is refused and an empty result is returned.

    Returns:
        A ``FetchResult`` describing the first matching result. On failure or
        when no results match, a result with empty URL/title is returned so
        callers do not crash.
    """
    if classification is not None and is_critical_category(classification):
        logger.warning("Web fetch refused for critical category: %s", classification.category)
        return _empty_result()

    try:
        url = _build_search_url(query)
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html",
            },
        )
        with urllib.request.urlopen(request, timeout=15.0) as response:
            html = response.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        logger.warning("Web fetch failed for query %r: %s", query, exc)
        return _empty_result()
    except Exception as exc:  # pragma: no cover - defensive catch-all
        logger.warning("Unexpected web fetch error for query %r: %s", query, exc)
        return _empty_result()

    parser = _DuckDuckGoResultParser()
    parser.feed(html)

    for record in parser.results:
        result_url = record.get("url", "")
        if not result_url:
            continue
        if _is_misinformation_domain(result_url):
            logger.warning("Dropping misinformation domain result: %s", result_url)
            continue
        if _matches_allowed_domains(result_url, allowed_domains or []):
            return FetchResult(
                url=result_url,
                title=record.get("title", ""),
                snippet=record.get("snippet", ""),
            )

    return _empty_result()


def _empty_result() -> FetchResult:
    return FetchResult(url="", title="No web sources found", snippet="")
