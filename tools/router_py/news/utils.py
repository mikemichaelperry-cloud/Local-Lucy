#!/usr/bin/env python3
"""News utility helpers."""

from __future__ import annotations

import html
import logging
import re
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


def _clean_html(text: str) -> str:
    """Remove HTML tags and decode common entities."""
    if not text:
        return ""
    # Remove HTML tags
    text = re.sub(r"<[^>]+>", "", text)
    # Decode common HTML entities
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&quot;", '"').replace("&#39;", "'")
    text = text.replace("&nbsp;", " ").replace("&#160;", " ")
    # Use html.unescape for any remaining entities
    text = html.unescape(text)
    # Normalize whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _parse_rfc822_date(date_str: str) -> datetime | None:
    """Parse an RFC 822 / ISO 8601 date string into a timezone-aware datetime.

    Returns None if the string cannot be parsed.
    """
    if not date_str:
        return None
    normalized = date_str.strip()
    if normalized.endswith(" GMT"):
        normalized = normalized[:-4] + " +0000"
    elif normalized.endswith(" UTC"):
        normalized = normalized[:-4] + " +0000"

    for fmt in [
        "%a, %d %b %Y %H:%M:%S %z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
    ]:
        try:
            dt = datetime.strptime(normalized, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def _query_asks_for_history(query: str) -> bool:
    """Return True if the query explicitly asks for historical news."""
    if not query:
        return False
    history_markers = {
        "history",
        "in 20",
        "during",
        "past",
        "old",
        "archived",
        "historical",
        "years ago",
        "decade",
        "century",
    }
    query_lower = query.lower()
    return any(marker in query_lower for marker in history_markers)


def _article_is_stale(pub_date: str, days: int = 7) -> bool:
    """Return True if the article is older than *days* days."""
    dt = _parse_rfc822_date(pub_date)
    if dt is None:
        return False
    now = datetime.now(timezone.utc)
    try:
        return (now - dt) > timedelta(days=days)
    except Exception:
        return False


def _format_time_ago(published: str) -> str:
    """Format publish time as 'X minutes/hours ago'."""
    try:
        normalized = published.strip()
        if normalized.endswith(" GMT"):
            normalized = normalized[:-4] + " +0000"
        elif normalized.endswith(" UTC"):
            normalized = normalized[:-4] + " +0000"

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

        if pub_time.tzinfo:
            now = datetime.now(pub_time.tzinfo)
        else:
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


def _detect_source_disagreement(articles: list[dict[str, Any]]) -> bool:
    """Detect whether sources report conflicting claims.

    Uses a lightweight keyword heuristic: if two different sources share a
    significant content word but one title uses a word and the other uses a
    known antonym/negation (e.g. "denies" vs "confirms"), flag disagreement.
    """
    if len(articles) < 2:
        return False

    # Pairs of contradictory stems/words commonly found in news headlines.
    antonym_pairs = [
        {"denies", "confirms"},
        {"rejects", "accepts", "approves"},
        {"falls", "drops", "rises", "gains", "soars"},
        {"attacks", "strike", "ceasefire", "truce"},
        {"war", "peace"},
        {"false", "true"},
        {"no", "yes"},
        {"guilty", "innocent"},
        {"accuses", "defends"},
    ]

    stopwords = {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "must",
        "shall",
        "can",
        "need",
        "dare",
        "ought",
        "used",
        "to",
        "of",
        "in",
        "for",
        "on",
        "with",
        "at",
        "by",
        "from",
        "as",
        "into",
        "through",
        "during",
        "before",
        "after",
        "above",
        "below",
        "between",
        "among",
        "and",
        "but",
        "or",
        "yet",
        "so",
        "if",
        "because",
        "although",
        "though",
        "while",
        "where",
        "when",
        "that",
        "which",
        "who",
        "whom",
        "whose",
        "what",
        "this",
        "these",
        "those",
        "i",
        "you",
        "he",
        "she",
        "it",
        "we",
        "they",
    }

    # Build per-source title tokens, keeping only meaningful words.
    source_titles: list[tuple[str, set[str], set[str]]] = []
    for article in articles:
        title = str(article.get("title", "")).lower()
        if not title:
            continue
        tokens = set(re.findall(r"[a-z][a-z']*", title))
        content_words = tokens - stopwords
        if not content_words:
            continue
        source_titles.append((article.get("source", ""), content_words, tokens))

    for i in range(len(source_titles)):
        for j in range(i + 1, len(source_titles)):
            src_i, words_i, raw_i = source_titles[i]
            src_j, words_j, raw_j = source_titles[j]
            if src_i == src_j:
                continue
            shared = words_i & words_j
            if len(shared) < 1:
                continue
            for pair in antonym_pairs:
                has_i = bool(raw_i & pair)
                has_j = bool(raw_j & pair)
                if has_i and has_j and not (raw_i & pair == raw_j & pair):
                    return True
    return False
