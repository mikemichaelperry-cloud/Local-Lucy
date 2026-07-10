#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


def _emit(payload: dict[str, Any], *, rc: int) -> int:
    print(json.dumps(payload))
    return rc


def _fail() -> int:
    return _emit({"ok": False}, rc=1)


def _http_json(url: str, timeout: float | None = None) -> dict:
    # The previous 2.5s default was too aggressive for Wikipedia's API,
    # especially when several sequential calls are made. Allow override via
    # environment and default to a more tolerant value.
    if timeout is None:
        try:
            timeout = float(
                os.environ.get("LUCY_UNVERIFIED_CONTEXT_WIKIPEDIA_TIMEOUT", "10.0").strip()
            )
        except ValueError:
            timeout = 10.0
        timeout = max(timeout, 2.5)
    request = urllib.request.Request(url, headers={"User-Agent": "LocalLucy/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8", errors="replace")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("expected JSON object")
    return parsed


# Common words that should not be used on their own to judge title relevance.
_STOP_WORDS = {
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
    "used",
    "to",
    "of",
    "in",
    "on",
    "at",
    "by",
    "for",
    "with",
    "about",
    "from",
    "up",
    "down",
    "out",
    "off",
    "over",
    "under",
    "again",
    "further",
    "then",
    "once",
    "here",
    "there",
    "when",
    "where",
    "why",
    "how",
    "all",
    "any",
    "both",
    "each",
    "few",
    "more",
    "most",
    "other",
    "some",
    "such",
    "no",
    "nor",
    "not",
    "only",
    "own",
    "same",
    "so",
    "than",
    "too",
    "very",
    "just",
    "now",
    "main",
    "popular",
    "famous",
    "best",
    "top",
    "list",
}

# Introductory phrases that should be stripped from natural-language queries.
_QUERY_PREFIXES = (
    r"what\s+(?:is|was|are|were|do|does|did|will|would|can|could|should|may|might)\s+",
    r"who\s+(?:is|was|are|were)\s+",
    r"where\s+(?:is|are|was|were)\s+",
    r"when\s+(?:is|was|were)\s+",
    r"why\s+(?:is|are|was|were|do|does|did)\s+",
    r"how\s+(?:is|are|was|were|do|does|did|can|could|should)\s+",
    r"which\s+(?:is|are|was|were)\s+",
    r"tell\s+me\s+(?:about|the\s+answer\s+to)\s+",
    r"give\s+me\s+(?:an?\s+overview\s+of|the\s+answer\s+to)\s+",
    r"overview\s+of\s+",
    r"history\s+of\s+",
    r"explain\s+",
    r"list\s+of\s+",
    r"(?:main|popular|famous|best)\s+",
    r"top\s+\d+\s+",
)


def _normalize_query(query: str) -> str:
    normalized = re.sub(r"\s+", " ", (query or "").strip())
    for prefix in _QUERY_PREFIXES:
        normalized = re.sub(
            rf"(?i)^(?:{prefix})",
            "",
            normalized,
            count=1,
        )
    # Drop a leading article so "the main tourist attractions in Japan"
    # becomes "main tourist attractions in Japan".
    normalized = re.sub(r"^(?:the|a|an)\s+", "", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"[?.!]+$", "", normalized).strip()
    return normalized or query


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip()).strip()


def _cache_ttl_seconds() -> int:
    raw = str(os.environ.get("LUCY_UNVERIFIED_CONTEXT_WIKIPEDIA_CACHE_TTL", "900")).strip()
    try:
        ttl = int(raw)
    except ValueError:
        ttl = 900
    return max(ttl, 0)


def _cache_file_for_query(query: str) -> Path | None:
    root = Path(os.environ.get("LUCY_ROOT", "")).expanduser()
    if not str(root):
        return None
    digest = hashlib.sha256(query.encode("utf-8")).hexdigest()
    return root / "state" / "cache" / "unverified_context_wikipedia" / f"{digest}.json"


def _load_cached_payload(query: str) -> dict[str, Any] | None:
    ttl = _cache_ttl_seconds()
    cache_file = _cache_file_for_query(query)
    if ttl <= 0 or cache_file is None or not cache_file.is_file():
        return None
    try:
        age_seconds = time.time() - cache_file.stat().st_mtime
        if age_seconds > ttl:
            return None
        payload = json.loads(cache_file.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    if not payload.get("ok"):
        return None
    text = _normalize_text(str(payload.get("text", "")))
    title = _normalize_text(str(payload.get("title", "")))
    if not text or not title:
        return None
    payload["provider"] = "wikipedia"
    payload["class"] = str(payload.get("class", "")).strip() or "wikipedia_general"
    payload["title"] = title
    payload["text"] = text
    payload["url"] = str(payload.get("url", "")).strip()
    return payload


def _store_cached_payload(query: str, payload: dict[str, Any]) -> None:
    ttl = _cache_ttl_seconds()
    cache_file = _cache_file_for_query(query)
    if ttl <= 0 or cache_file is None:
        return
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(payload), encoding="utf-8")
    except Exception:
        return


def _success_payload(*, title: str, url: str, text: str) -> dict[str, Any]:
    return {
        "ok": True,
        "class": "wikipedia_general",
        "provider": "wikipedia",
        "title": _normalize_text(title),
        "url": str(url or "").strip(),
        "text": _normalize_text(text),
    }


def _extract_place_tail(query: str) -> str | None:
    """Extract a trailing place/topic phrase after 'in' or 'of'.

    Examples:
      'main tourist attractions in Japan' -> 'Japan'
      'capital of France'                 -> 'France'
      'president of the United States'    -> 'United States'
    """
    match = re.search(r"\b(?:in|of)\s+([A-Za-z][A-Za-z\s]*?)\s*$", query)
    if not match:
        return None
    tail = match.group(1).strip()
    tail = re.sub(r"^(?:the|a|an)\s+", "", tail, flags=re.IGNORECASE).strip()
    tail = re.sub(r"\s+(?:today|now|currently|right\s+now)$", "", tail, flags=re.IGNORECASE).strip()
    return tail if tail else None


def _is_tourism_query(query: str) -> bool:
    q = query.lower()
    return any(term in q for term in ("tourism", "tourist", "attraction", "sightsee", "vacation"))


def _title_matches_query(title: str, query: str, tail: str | None = None) -> bool:
    """Return True if the fetched article title is plausibly about the query.

    If the query names a place/topic tail (e.g. 'Japan'), require the title to
    contain it. Otherwise fall back to keyword overlap.
    """
    title_lower = title.lower()
    if tail:
        # Accept both the tail and a hyphen/compact form like 'Japan-U.S.'
        if tail.lower() in title_lower:
            return True
        # Allow the tail to be split if it is multi-word ('United States').
        tail_parts = [p for p in re.split(r"\s+", tail.lower()) if p not in _STOP_WORDS]
        if len(tail_parts) > 1 and all(part in title_lower for part in tail_parts):
            return True
        return False

    # No place tail: check that at least one meaningful keyword appears.
    words = [
        w for w in re.findall(r"[a-zA-Z]+", query.lower()) if len(w) > 3 and w not in _STOP_WORDS
    ]
    return any(w in title_lower for w in words)


def _try_direct_summary(title: str, lang: str = "en") -> dict[str, Any] | None:
    """Fetch a Wikipedia page summary by exact page title."""
    if not title:
        return None
    try:
        url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(
            title, safe=""
        )
        payload = _http_json(url)
        extract = _normalize_text(str(payload.get("extract", "")))
        canonical_url = str(
            ((payload.get("content_urls") or {}).get("desktop") or {}).get("page", "")
        ).strip()
        title = _normalize_text(str(payload.get("title", "")))
        if extract and title:
            return _success_payload(title=title, url=canonical_url, text=extract)
    except Exception:
        pass
    return None


def _try_search(query: str, lang: str = "en") -> dict[str, Any] | None:
    """Search Wikipedia and return the top article summary."""
    if not query:
        return None
    try:
        url = (
            f"https://{lang}.wikipedia.org/w/api.php?action=query&format=json&list=search&srlimit=1&srsearch="
            + urllib.parse.quote(query, safe="")
        )
        payload = _http_json(url)
        items = ((payload.get("query") or {}).get("search")) or []
        if not items:
            return None
        first = items[0] if isinstance(items[0], dict) else {}
        title = _normalize_text(str(first.get("title", "")))
        if not title:
            return None
        return _try_direct_summary(title, lang=lang)
    except Exception:
        return None


def _fetch_wikipedia_context(query: str, lang: str = "en") -> dict[str, Any] | None:
    """Fetch a relevant Wikipedia article for *query* with a place/topic fallback.

    Natural-language queries such as "What are the main tourist attractions in
    Japan?" often return an unrelated top search result (e.g. Tourism in China).
    We therefore validate the top result's title and, when it does not match the
    query, try a more targeted lookup using the trailing place/topic phrase.
    """
    tail = _extract_place_tail(query)

    # 1. Direct summary by the (cleaned) query title.
    result = _try_direct_summary(query, lang=lang)
    if result is not None and _title_matches_query(result["title"], query, tail):
        return result

    # 2. Wikipedia search for the cleaned query.
    result = _try_search(query, lang=lang)
    if result is not None and _title_matches_query(result["title"], query, tail):
        return result

    # 3. Fallback to the trailing place/topic, with a tourism-specific rewrite.
    if tail:
        fallback_queries = []
        if _is_tourism_query(query):
            fallback_queries.append(f"Tourism in {tail}")
        fallback_queries.append(tail)

        for fallback in fallback_queries:
            # Skip if we already tried this exact string as the cleaned query.
            if fallback.lower() == query.lower():
                continue
            result = _try_direct_summary(fallback, lang=lang)
            if result is not None and _title_matches_query(result["title"], query, tail):
                return result
            result = _try_search(fallback, lang=lang)
            if result is not None and _title_matches_query(result["title"], query, tail):
                return result

    # No relevant article found.
    return None


def fetch_context(query: str) -> dict[str, Any]:
    normalized_query = _normalize_query(query)

    mock_text = os.environ.get("LUCY_UNVERIFIED_CONTEXT_MOCK_TEXT", "").strip()
    mock_url = os.environ.get("LUCY_UNVERIFIED_CONTEXT_MOCK_URL", "").strip()
    if mock_text:
        payload = _success_payload(title="Mock", url=mock_url, text=mock_text)
        _store_cached_payload(normalized_query, payload)
        return payload

    cached_payload = _load_cached_payload(normalized_query)
    if cached_payload is not None:
        return cached_payload

    result = _fetch_wikipedia_context(normalized_query, lang="en")
    if result is not None:
        _store_cached_payload(normalized_query, result)
        return result
    return {"ok": False}


def main() -> int:
    query = " ".join(sys.argv[1:]).strip()
    if not query:
        return _fail()

    payload = fetch_context(query)
    if not payload.get("ok"):
        return _fail()
    return _emit(payload, rc=0)


if __name__ == "__main__":
    raise SystemExit(main())
