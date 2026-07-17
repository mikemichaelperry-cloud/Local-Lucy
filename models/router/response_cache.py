#!/usr/bin/env python3
"""In-memory response cache with TTL — skip LLM for repeated queries.

Only caches LOCAL route responses. AUGMENTED / NEWS / TIME are inherently
dynamic and never cached. Cache key is the normalized query string.

Usage:
    from response_cache import get_cached, set_cached, maybe_cache_response
    cached = get_cached("what is 2+2?")
    if cached:
        return cached
    response = await call_llm(query)
    set_cached(query, response, route="LOCAL")
"""

from __future__ import annotations

import os
import re
import time
from collections import OrderedDict
from typing import Any

# Config (overridable via env vars)
MAX_CACHE_SIZE = int(os.environ.get("LUCY_CACHE_MAX_SIZE", "256"))
DEFAULT_TTL_SECONDS = int(os.environ.get("LUCY_CACHE_TTL_SECONDS", "300"))

# Cache: OrderedDict preserves insertion order for LRU eviction
# Value: (response_text, expiry_timestamp)
_cache: OrderedDict[str, tuple[str, float]] = OrderedDict()

# Metrics
_hits = 0
_misses = 0


def _normalize_key(query: str) -> str:
    """Normalize query for cache key: lowercase, collapse whitespace, strip punctuation."""
    q = query.lower().strip()
    q = re.sub(r"[^\w\s]", "", q)
    q = re.sub(r"\s+", " ", q)
    return q


def get_cached(query: str) -> str | None:
    """Return cached response if present and not expired."""
    global _hits, _misses
    key = _normalize_key(query)
    if key not in _cache:
        _misses += 1
        return None
    response, expiry = _cache[key]
    if time.time() > expiry:
        _misses += 1
        del _cache[key]
        return None
    # Move to end (most recently used)
    _cache.move_to_end(key)
    _hits += 1
    return response


def set_cached(
    query: str, response: str, route: str = "LOCAL", ttl: int = DEFAULT_TTL_SECONDS
) -> None:
    """Store response in cache if route is cacheable.

    Args:
        query: Original user query
        response: LLM response text
        route: Routing decision (only LOCAL is cached)
        ttl: Time-to-live in seconds
    """
    if route not in ("LOCAL",):
        return
    if not query or not response:
        return
    # Don't cache error responses
    if response.startswith("Error:") or len(response) < 10:
        return

    key = _normalize_key(query)
    expiry = time.time() + ttl

    # Evict oldest if at capacity
    if len(_cache) >= MAX_CACHE_SIZE and key not in _cache:
        _cache.popitem(last=False)

    _cache[key] = (response, expiry)
    _cache.move_to_end(key)


def cache_stats() -> dict[str, Any]:
    """Return cache statistics."""
    now = time.time()
    valid = sum(1 for _, expiry in _cache.values() if expiry > now)
    expired = len(_cache) - valid
    total = _hits + _misses
    hit_rate = round(_hits / total, 3) if total > 0 else 0.0
    return {
        "size": len(_cache),
        "valid": valid,
        "expired": expired,
        "max_size": MAX_CACHE_SIZE,
        "ttl_seconds": DEFAULT_TTL_SECONDS,
        "hits": _hits,
        "misses": _misses,
        "hit_rate": hit_rate,
    }


def clear_cache() -> None:
    """Clear all cached entries."""
    _cache.clear()
