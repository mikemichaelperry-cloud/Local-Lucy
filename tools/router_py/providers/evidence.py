"""
Evidence fetchers for external data sources.

These are async functions that fetch evidence from Wikipedia, API providers,
weather, time, and news sources. They are stateless and accept explicit
parameters rather than depending on ExecutionEngine instance state.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent

# Idempotent sys.path helper to avoid O(n) duplicate inserts
_TOOLS_PATH_STR = str(ROOT_DIR / "tools")


def _ensure_tools_path() -> None:
    if _TOOLS_PATH_STR not in sys.path:
        sys.path.insert(0, _TOOLS_PATH_STR)


# Optional imports
try:
    from router_py.news_provider import NewsProvider
    HAS_NEWS_PROVIDER = True
except ImportError:
    HAS_NEWS_PROVIDER = False

# ── Evidence TTL cache (Phase 2D) ──────────────────────────────────────────────
# Caches successful evidence fetches to avoid redundant external calls.
#   wikipedia: 1 hour (deterministic, mostly static)
#   time:      60 seconds (time changes continuously)
#   weather:   5 minutes (weather changes)
# News, API (Kimi/OpenAI), and trusted (medical/veterinary) are NOT cached
# for freshness / safety reasons.
_EVIDENCE_CACHE: dict[str, tuple[Any, float]] = {}
_EVIDENCE_CACHE_MAXSIZE = 256
_EVIDENCE_CACHE_TTL: dict[str, float] = {
    "wikipedia": 3600.0,
    "time": 60.0,
    "weather": 300.0,
}


def _evidence_cache_key(provider: str, question: str) -> str:
    return f"{provider}:{question.strip().lower()}"


def _get_cached_evidence(provider: str, question: str) -> Any:
    key = _evidence_cache_key(provider, question)
    entry = _EVIDENCE_CACHE.get(key)
    if entry is None:
        return None
    result, expiry = entry
    if time.time() > expiry:
        _EVIDENCE_CACHE.pop(key, None)
        return None
    return result


def _set_cached_evidence(provider: str, question: str, result: Any) -> None:
    if result is None:
        return
    ttl = _EVIDENCE_CACHE_TTL.get(provider, 0.0)
    if ttl <= 0.0:
        return
    key = _evidence_cache_key(provider, question)
    _EVIDENCE_CACHE[key] = (result, time.time() + ttl)
    # Simple LRU trim per provider prefix
    prefix = provider + ":"
    provider_keys = [k for k in _EVIDENCE_CACHE if k.startswith(prefix)]
    overage = len(provider_keys) - _EVIDENCE_CACHE_MAXSIZE
    if overage > 0:
        for k in provider_keys[:overage]:
            _EVIDENCE_CACHE.pop(k, None)


def _prepare_subprocess_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Build isolated subprocess environment."""
    import os
    env = os.environ.copy()
    env["STATE_NAMESPACE_RAW"] = os.environ.get("LUCY_SHARED_STATE_NAMESPACE", "")
    if extra:
        env.update(extra)
    return env


async def fetch_wikipedia_evidence(question: str) -> dict[str, Any] | None:
    """Fetch evidence from Wikipedia."""
    cached = _get_cached_evidence("wikipedia", question)
    if cached is not None:
        logger.debug("Wikipedia evidence cache hit")
        return cached

    logger.debug(f"Fetching Wikipedia evidence for: {question[:50]}...")
    result = None
    try:
        _ensure_tools_path()
        import unverified_context_wikipedia as wiki_provider
        loop = asyncio.get_event_loop()
        payload = await loop.run_in_executor(None, wiki_provider.fetch_context, question)
        if payload and payload.get("ok"):
            result = {
                "context": payload.get("text", ""),
                "title": payload.get("title", ""),
                "url": payload.get("url", ""),
                "provider": "wikipedia",
                "class": payload.get("class", "wikipedia_general"),
            }
    except Exception as e:
        logger.warning(f"Wikipedia evidence fetch failed: {e}")

    _set_cached_evidence("wikipedia", question, result)
    return result


async def fetch_news_evidence(question: str, for_voice: bool = False) -> dict[str, Any] | None:
    """Fetch live news from RSS feeds."""
    if not HAS_NEWS_PROVIDER:
        logger.warning("News provider not available")
        return None

    import time
    fetch_start = time.time()
    try:
        result = await NewsProvider.fetch_news(question, for_voice=for_voice)
        elapsed = time.time() - fetch_start
        if result.ok:
            article_count = len(result.articles) if result.articles else 0
            logger.info(
                f"NEWS fetched fresh: {article_count} articles in {elapsed:.2f}s "
                f"(partial={result.partial}, source={result.source})"
            )
            return {
                "context": result.text,
                "html_context": result.html_text,
                "title": "Latest News",
                "url": "",
                "provider": result.source,
                "class": "news_live",
                "articles": result.articles,
                "partial": result.partial,
                "errors": result.errors,
            }
        else:
            logger.warning(f"News fetch failed after {elapsed:.2f}s: {result.error}")
            return None
    except Exception as e:
        elapsed = time.time() - fetch_start
        logger.warning(f"News evidence fetch failed after {elapsed:.2f}s: {e}")
        return None


async def fetch_time_evidence(question: str) -> dict[str, Any] | None:
    """Fetch current time from TimeAPI.io."""
    cached = _get_cached_evidence("time", question)
    if cached is not None:
        logger.debug("Time evidence cache hit")
        return cached

    import re

    # Extract location from question
    location = None
    patterns = [
        r"(?:what['']?s?|what is|current)\s+time\s+(?:is it\s+)?(?:in|at)\s+([^?]+)",
        r"time\s+(?:in|at)\s+([^?]+)",
        r"(?:in|at)\s+([^?]+)\s+time",
    ]
    for pattern in patterns:
        match = re.search(pattern, question, re.IGNORECASE)
        if match:
            candidate = match.group(1).strip()
            blacklist = {"a", "an", "the", "it", "that", "this", "what",
                         "me", "my", "your", "you", "he", "him", "his",
                         "she", "her", "they", "them", "their", "we", "us",
                         "no", "not", "all", "same", "just", "now", "then",
                         "here", "there", "when", "where", "why", "how",
                         "in", "at", "on", "by", "for", "with", "to", "of"}
            if candidate.lower() not in blacklist and len(candidate) > 1:
                location = candidate
                break

    # Default to system local timezone if no location found
    if not location:
        try:
            import datetime as _dt
            tz = _dt.datetime.now().astimezone().tzinfo
            if tz and hasattr(tz, 'key'):
                location = tz.key
            else:
                location = "UTC"
        except Exception:
            location = "UTC"

    logger.info(f"Fetching time for location: {location}")

    try:
        tool_path = ROOT_DIR / "tools" / "current_time_tool.py"
        if not tool_path.exists():
            logger.warning("Time tool not found")
            return None

        proc = await asyncio.create_subprocess_exec(
            sys.executable, str(tool_path), location,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(ROOT_DIR),
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10.0)
        except asyncio.TimeoutError:
            proc.kill()
            logger.warning("Time tool timed out")
            return None

        result = None
        if proc.returncode == 0:
            data = json.loads(stdout.decode('utf-8'))
            if data.get("ok"):
                formatted = format_time_response(data)
                result = {
                    "ok": True,
                    "timezone": data.get("timezone"),
                    "datetime": data.get("datetime"),
                    "dst": data.get("dst"),
                    "formatted": formatted,
                }
            else:
                logger.warning(f"Time API error: {data.get('error')}")
        else:
            logger.warning(f"Time tool failed: {stderr.decode()}")
        _set_cached_evidence("time", question, result)
        return result
    except Exception as e:
        logger.warning(f"Time evidence fetch failed: {e}")
        return None


def format_time_response(data: dict) -> str:
    """Format time API response into human-readable text."""
    try:
        time_str = data.get("time", "?")
        date_str = data.get("date", "?")
        timezone = data.get("timezone", "Unknown")
        day = data.get("day_of_week", "")
        dst = data.get("dst", False)

        hour = int(data.get("hour", 0))
        minute = int(data.get("minute", 0))
        ampm = "AM" if hour < 12 else "PM"
        hour_12 = hour if hour <= 12 else hour - 12
        if hour_12 == 0:
            hour_12 = 12
        time_formatted = f"{hour_12}:{minute:02d} {ampm}"

        lines = [
            f"The current time in {timezone} is {time_formatted}.",
            f"Date: {day}, {date_str}",
        ]
        if dst:
            lines.append("Daylight Saving Time is currently active.")

        return "\n".join(lines)
    except Exception:
        return f"Current time: {data.get('time', 'unknown')}"


async def fetch_weather_evidence(question: str) -> dict[str, Any] | None:
    """Fetch weather data from wttr.in."""
    cached = _get_cached_evidence("weather", question)
    if cached is not None:
        logger.debug("Weather evidence cache hit")
        return cached

    try:
        # Robust import: works regardless of sys.path configuration
        try:
            from router_py.weather_provider import fetch_weather
        except ImportError:
            from weather_provider import fetch_weather
        result = await fetch_weather(question)
        _set_cached_evidence("weather", question, result)
        return result
    except Exception as e:
        logger.warning(f"Weather evidence fetch failed: {e}")
        return None


async def fetch_api_evidence(
    question: str,
    provider: str,
    timeout: float = 130.0,
) -> dict[str, Any] | None:
    """Fetch evidence from API provider (Kimi or OpenAI)."""
    logger.debug(f"Fetching {provider} evidence for: {question[:50]}...")
    try:
        _ensure_tools_path()
        loop = asyncio.get_event_loop()
        if provider == "kimi":
            return await loop.run_in_executor(
                None, call_kimi_subprocess, question, timeout
            )
        elif provider == "openai":
            return await loop.run_in_executor(
                None, call_openai_subprocess, question, timeout
            )
        return None
    except Exception as e:
        logger.warning(f"{provider} evidence fetch failed: {e}")
        return None


def call_kimi_subprocess(question: str, timeout: float = 130.0) -> dict[str, Any] | None:
    """Call Kimi provider via subprocess (sync version for thread pool)."""
    import subprocess
    tool = ROOT_DIR / "tools" / "unverified_context_kimi.py"
    if not tool.exists():
        return None
    try:
        result = subprocess.run(
            [sys.executable, str(tool), question],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_prepare_subprocess_env(),
            cwd=str(ROOT_DIR),
        )
        if result.returncode == 0:
            payload = json.loads(result.stdout)
            if payload.get("ok"):
                return {
                    "context": payload.get("text", payload.get("context", "")),
                    "title": payload.get("title", ""),
                    "url": payload.get("url", ""),
                    "provider": "kimi",
                    "class": payload.get("class", "kimi_general"),
                }
    except Exception as e:
        logger.debug(f"Kimi subprocess failed: {e}")
    return None


def call_openai_subprocess(question: str, timeout: float = 130.0) -> dict[str, Any] | None:
    """Call OpenAI provider via subprocess (sync version for thread pool)."""
    import subprocess
    tool = ROOT_DIR / "tools" / "unverified_context_openai.py"
    if not tool.exists():
        return None
    try:
        result = subprocess.run(
            [sys.executable, str(tool), question],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_prepare_subprocess_env(),
            cwd=str(ROOT_DIR),
        )
        if result.returncode == 0:
            payload = json.loads(result.stdout)
            if payload.get("ok"):
                return {
                    "context": payload.get("text", payload.get("context", "")),
                    "title": payload.get("title", ""),
                    "url": payload.get("url", ""),
                    "provider": "openai",
                    "class": payload.get("class", "openai_general"),
                }
    except Exception as e:
        logger.debug(f"OpenAI subprocess failed: {e}")
    return None


async def fetch_trusted_evidence(
    question: str,
    route: Any,
) -> dict[str, Any] | None:
    """Fetch evidence from trusted sources (medical/veterinary domains).
    
    Uses unverified_context_trusted.py with domain restrictions.
    Returns None if no evidence found, signaling strict enforcement.
    """
    logger.debug(f"Fetching trusted evidence for: {question[:50]}...")
    try:
        _ensure_tools_path()
        import unverified_context_trusted as trusted_provider
        loop = asyncio.get_event_loop()
        intent_family = route.intent_family if route else ""
        evidence_reason = route.evidence_reason if route else ""
        payload = await loop.run_in_executor(
            None, trusted_provider.fetch_context, question, intent_family, evidence_reason
        )
        if payload and payload.get("ok"):
            evidence = {
                "context": payload.get("content", ""),
                "title": payload.get("category", "Trusted Sources"),
                "url": "",
                "provider": "trusted",
                "class": payload.get("category", "trusted_general"),
                "sources": payload.get("sources", []),
                "bounded_response": payload.get("bounded_response", False),
            }
            # Pass through fallback telemetry fields from trusted provider metadata
            for key in ("fallback_used", "fallback_reason", "primary_failed",
                        "fallback_to", "attempted_chain", "successful_backend",
                        "degradation_level", "answer_basis", "DEGRADED_REASON"):
                if key in payload:
                    evidence[key] = payload[key]
            return evidence
        return None
    except Exception as e:
        logger.warning(f"Trusted evidence fetch failed: {e}")
        return None
