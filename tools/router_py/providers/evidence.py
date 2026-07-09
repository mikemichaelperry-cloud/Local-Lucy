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
import os
import re
import sys
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
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
    """Build isolated subprocess environment (retained for API compatibility)."""

    env = os.environ.copy()
    env["STATE_NAMESPACE_RAW"] = os.environ.get("LUCY_SHARED_STATE_NAMESPACE", "")
    if extra:
        env.update(extra)
    return env


def _is_medical_vet_finance_evidence(evidence: dict[str, Any], route: Any = None) -> bool:
    """Return True if the evidence belongs to a freshness-sensitive domain."""
    if not isinstance(evidence, dict):
        return False
    text = " ".join(
        str(evidence.get(k, "")).lower()
        for k in ("class", "provider", "category", "source", "title")
    )
    if route is not None:
        reason = str(getattr(route, "evidence_reason", "")).lower()
        text += " " + reason
    return any(
        marker in text
        for marker in (
            "medical",
            "veterinary",
            "vet",
            "finance",
            "financial",
            "personal_finance",
        )
    )


def _parse_evidence_date(evidence: dict[str, Any]) -> datetime | None:
    """Best-effort extraction of an evidence date."""
    if not isinstance(evidence, dict):
        return None
    for key in ("date", "published", "datetime", "source_age_days", "timestamp"):
        value = evidence.get(key)
        if value is None:
            continue
        if key == "source_age_days":
            try:
                age_days = int(value)
                return datetime.now(timezone.utc) - timedelta(days=age_days)
            except Exception:
                continue
        parsed = _parse_date_value(str(value))
        if parsed is not None:
            return parsed
    return None


def _parse_date_value(value: str) -> datetime | None:
    """Parse a single date string; returns timezone-aware UTC datetime or None."""
    if not value or value.lower() in ("unknown", "n/a", ""):
        return None
    # ISO 8601 / common RFC variants
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%a, %d %b %Y %H:%M:%S %z",
    ):
        try:
            dt = datetime.strptime(value, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            continue
    # Fallback to dateutil if available
    try:
        from dateutil import parser as dateutil_parser

        dt = dateutil_parser.parse(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _apply_evidence_freshness(
    evidence: dict[str, Any],
    route: Any = None,
    stale_days: int = 365,
) -> dict[str, Any]:
    """Set fresh/confidence flags on medical/vet/finance evidence.

    If the evidence is older than *stale_days* days, mark it fresh=False and
    reduce the confidence. Non-sensitive domains are left unchanged.
    """
    if not isinstance(evidence, dict):
        return evidence
    if not _is_medical_vet_finance_evidence(evidence, route=route):
        return evidence

    parsed = _parse_evidence_date(evidence)
    age_days = None
    if parsed is not None:
        age_days = (datetime.now(timezone.utc) - parsed).days
    elif "source_age_days" in evidence:
        try:
            age_days = int(evidence["source_age_days"])
        except Exception:
            pass

    if age_days is not None and age_days > stale_days:
        evidence["fresh"] = False
        evidence["source_age_days"] = age_days
        evidence["confidence"] = max(0.0, min(1.0, float(evidence.get("confidence", 0.8)) * 0.7))
    else:
        evidence["fresh"] = True
        if age_days is not None:
            evidence["source_age_days"] = age_days
    return evidence


def _local_with_caveat_fallback(
    question: str = "",
    reason: str = "no_live_source",
) -> dict[str, Any]:
    """Return a structured fallback dict for when live sources are unavailable."""
    return {
        "fallback": True,
        "suggested_action": "local_with_caveat",
        "fallback_reason": reason,
        "context": "",
        "content": "",
        "formatted": "",
        "title": "Live source unavailable",
        "url": "",
        "provider": "local",
        "class": "local_fallback",
    }


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

    result = _apply_evidence_freshness(result)
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
                "disagreement": result.disagreement,
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
            blacklist = {
                "a",
                "an",
                "the",
                "it",
                "that",
                "this",
                "what",
                "me",
                "my",
                "your",
                "you",
                "he",
                "him",
                "his",
                "she",
                "her",
                "they",
                "them",
                "their",
                "we",
                "us",
                "no",
                "not",
                "all",
                "same",
                "just",
                "now",
                "then",
                "here",
                "there",
                "when",
                "where",
                "why",
                "how",
                "in",
                "at",
                "on",
                "by",
                "for",
                "with",
                "to",
                "of",
            }
            if candidate.lower() not in blacklist and len(candidate) > 1:
                location = candidate
                break

    # Default to system local timezone if no location found
    if not location:
        try:
            import datetime as _dt

            tz = _dt.datetime.now().astimezone().tzinfo
            if tz and hasattr(tz, "key"):
                location = tz.key
            else:
                location = "UTC"
        except Exception:
            location = "UTC"

    logger.info(f"Fetching time for location: {location}")

    try:
        _ensure_tools_path()
        import current_time_tool

        data = current_time_tool.get_current_time(location)
        result = None
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
            return await loop.run_in_executor(None, call_kimi_subprocess, question, timeout)
        elif provider == "openai":
            return await loop.run_in_executor(None, call_openai_subprocess, question, timeout)
        return None
    except Exception as e:
        logger.warning(f"{provider} evidence fetch failed: {e}")
        return None


def call_kimi_subprocess(question: str, timeout: float = 130.0) -> dict[str, Any] | None:
    """Call Kimi provider directly (sync version for thread pool)."""
    try:
        _ensure_tools_path()
        import unverified_context_kimi as kimi_provider

        payload = kimi_provider.answer_question(question)
        if payload.get("ok"):
            return {
                "context": payload.get("text", payload.get("context", "")),
                "title": payload.get("title", ""),
                "url": payload.get("url", ""),
                "provider": "kimi",
                "class": payload.get("class", "kimi_general"),
            }
    except Exception as e:
        logger.debug(f"Kimi direct call failed: {e}")
    return None


def call_openai_subprocess(question: str, timeout: float = 130.0) -> dict[str, Any] | None:
    """Call OpenAI provider directly (sync version for thread pool)."""
    try:
        _ensure_tools_path()
        import unverified_context_openai as openai_provider

        payload = openai_provider.answer_question(question)
        if payload.get("ok"):
            return {
                "context": payload.get("text", payload.get("context", "")),
                "title": payload.get("title", ""),
                "url": payload.get("url", ""),
                "provider": "openai",
                "class": payload.get("class", "openai_general"),
            }
    except Exception as e:
        logger.debug(f"OpenAI direct call failed: {e}")
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
            for key in (
                "fallback_used",
                "fallback_reason",
                "primary_failed",
                "fallback_to",
                "attempted_chain",
                "successful_backend",
                "degradation_level",
                "answer_basis",
                "DEGRADED_REASON",
            ):
                if key in payload:
                    evidence[key] = payload[key]
            return _apply_evidence_freshness(evidence, route=route)
        return _local_with_caveat_fallback(question, reason="trusted_source_unavailable")
    except Exception as e:
        logger.warning(f"Trusted evidence fetch failed: {e}")
        return _local_with_caveat_fallback(question, reason=f"trusted_fetch_error:{e}")


# ---------------------------------------------------------------------------
# Finance data fetcher
# ---------------------------------------------------------------------------

_FINANCE_COMMON_TICKERS = {
    "apple": "AAPL",
    "microsoft": "MSFT",
    "amazon": "AMZN",
    "google": "GOOGL",
    "alphabet": "GOOGL",
    "nvidia": "NVDA",
    "tesla": "TSLA",
    "meta": "META",
    "facebook": "META",
    "netflix": "NFLX",
    "s&p 500": "^GSPC",
    "nasdaq": "^IXIC",
    "dow jones": "^DJI",
    "ftse": "^FTSE",
    "nikkei": "^N225",
}

# CoinGecko id mapping for common crypto names/tickers
_FINANCE_CRYPTO_IDS = {
    "bitcoin": "bitcoin",
    "btc": "bitcoin",
    "ethereum": "ethereum",
    "eth": "ethereum",
    "solana": "solana",
    "sol": "solana",
    "ripple": "ripple",
    "xrp": "ripple",
    "cardano": "cardano",
    "ada": "cardano",
    "dogecoin": "dogecoin",
    "doge": "dogecoin",
}

_FINANCE_CURRENCY_CODES = {
    "dollar": "USD",
    "usd": "USD",
    "$": "USD",
    "euro": "EUR",
    "eur": "EUR",
    "€": "EUR",
    "pound": "GBP",
    "gbp": "GBP",
    "£": "GBP",
    "yen": "JPY",
    "jpy": "JPY",
    "¥": "JPY",
    "shekel": "ILS",
    "ils": "ILS",
    "₪": "ILS",
    "canadian dollar": "CAD",
    "cad": "CAD",
    "c$": "CAD",
    "australian dollar": "AUD",
    "aud": "AUD",
    "a$": "AUD",
    "swiss franc": "CHF",
    "chf": "CHF",
}


def _match_exchange_rate(question: str) -> dict[str, str] | None:
    """Detect exchange-rate queries like 'EUR to USD' or 'euro to dollar'."""
    q = question.lower()
    # Pattern: <code/word> to <code/word>
    match = re.search(r"(\b[a-z$€£¥₪]+\b)\s+to\s+(\b[a-z$€£¥₪]+\b)", q)
    if not match:
        return None
    base_word, target_word = match.group(1), match.group(2)
    base = _FINANCE_CURRENCY_CODES.get(base_word, base_word.upper())
    target = _FINANCE_CURRENCY_CODES.get(target_word, target_word.upper())
    if len(base) == 3 and len(target) == 3:
        return {"base": base, "target": target}
    return None


def _extract_stock_symbol(question: str) -> str | None:
    """Extract a ticker symbol or mapped company name from a finance query."""
    q = question.lower()

    # Explicit ticker in uppercase (e.g., "TSLA", "AAPL")
    ticker_match = re.search(r"\b([A-Z]{1,5}(?:-USD)?)\b", question)
    if ticker_match and ticker_match.group(1).upper() not in {"I", "A", "USD", "EUR", "GBP"}:
        return ticker_match.group(1).upper()

    # Known company / index names
    for name, ticker in _FINANCE_COMMON_TICKERS.items():
        if name in q:
            return ticker

    # "X stock price" / "X share price" / "X stock"
    for pattern in [
        r"([a-z]+)\s+stock\s+price",
        r"([a-z]+)\s+share\s+price",
        r"([a-z]+)\s+stock\b",
    ]:
        match = re.search(pattern, q)
        if match:
            name = match.group(1)
            if name in _FINANCE_COMMON_TICKERS:
                return _FINANCE_COMMON_TICKERS[name]
            if name in _FINANCE_CRYPTO_IDS:
                return name.upper()

    # Crypto-only patterns: "X price" / "X crypto"
    for pattern in [
        r"\b(bitcoin|ethereum|solana|ripple|cardano|dogecoin|btc|eth|sol|xrp|ada|doge)\s+price\b",
        r"\b(bitcoin|ethereum|solana|ripple|cardano|dogecoin|btc|eth|sol|xrp|ada|doge)\s+crypto\b",
    ]:
        match = re.search(pattern, q)
        if match:
            return match.group(1).upper()
    return None


def _extract_net_worth_person(question: str) -> str | None:
    """Extract a person's name from net-worth queries."""
    q = question.lower().replace("'s", "")
    patterns = [
        r"how much is ([a-z]+(?:\s+[a-z]+){0,2}) worth",
        r"how much is ([a-z]+(?:\s+[a-z]+){0,2}) valued at",
        r"(?:^|\b(?:what|who|where|when|how much)\s+is\s+)?([a-z]+(?:\s+[a-z]+){0,2})\s+net worth",
        r"net worth of ([a-z]+(?:\s+[a-z]+){0,2})",
    ]
    for pattern in patterns:
        match = re.search(pattern, q)
        if match:
            person = match.group(1).strip()
            # Drop any leading interrogative/auxiliary words that bled into the capture.
            stop_leaders = {"is", "what", "who", "where", "when", "how", "much"}
            parts = person.split()
            while parts and parts[0] in stop_leaders:
                parts.pop(0)
            person = " ".join(parts)
            if person and person not in {"it", "he", "she", "they", "this", "that"}:
                return person.title()
    return None


def _fetch_exchange_rate(base: str, target: str) -> dict[str, Any] | None:
    """Fetch exchange rate from exchangerate-api.com (free, no key)."""
    url = f"https://api.exchangerate-api.com/v4/latest/{base}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Local-Lucy/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        rate = data.get("rates", {}).get(target)
        if rate is None:
            return None
        formatted = f"1 {base} = {rate:.4f} {target} (as of {data.get('date', 'unknown')})"
        return {
            "ok": True,
            "context": formatted,
            "formatted": formatted,
            "title": f"{base}/{target} Exchange Rate",
            "url": url,
            "provider": "finance",
            "source": "exchangerate-api.com",
            "base": base,
            "target": target,
            "rate": rate,
            "class": "finance_exchange_rate",
        }
    except Exception as e:
        logger.warning(f"Exchange rate fetch failed: {e}")
    return None


def _fetch_yahoo_finance(symbol: str) -> dict[str, Any] | None:
    """Fetch latest price from Yahoo Finance chart API (unofficial endpoint)."""
    encoded = urllib.parse.quote(symbol)
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?interval=1d&range=1d"
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        result = data.get("chart", {}).get("result", [None])[0]
        if not result:
            return None
        meta = result.get("meta", {})
        price = meta.get("regularMarketPrice")
        prev_close = meta.get("previousClose") or meta.get("chartPreviousClose")
        currency = meta.get("currency", "USD")
        exchange = meta.get("exchangeName", "")
        if price is None:
            return None
        change = price - prev_close if prev_close else 0
        pct = (change / prev_close * 100) if prev_close else 0
        change_str = f"{change:+.2f} ({pct:+.2f}%)" if prev_close else "n/a"
        formatted = f"{symbol}: {price:.2f} {currency} ({change_str})"
        if exchange:
            formatted += f" on {exchange}"
        return {
            "ok": True,
            "context": formatted,
            "formatted": formatted,
            "title": f"{symbol} Quote",
            "url": f"https://finance.yahoo.com/quote/{encoded}",
            "provider": "finance",
            "source": "Yahoo Finance",
            "symbol": symbol,
            "price": price,
            "currency": currency,
            "class": "finance_quote",
        }
    except Exception as e:
        logger.warning(f"Yahoo Finance fetch failed for {symbol}: {e}")
    return None


def _fetch_coingecko(symbol: str) -> dict[str, Any] | None:
    """Fetch latest crypto price from CoinGecko (free, no key)."""
    coin_id = _FINANCE_CRYPTO_IDS.get(symbol.lower())
    if not coin_id:
        return None
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd&include_24hr_change=true"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Local-Lucy/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        info = data.get(coin_id)
        if not info:
            return None
        price = info.get("usd")
        change_pct = info.get("usd_24h_change")
        if price is None:
            return None
        change_str = f"{change_pct:+.2f}% (24h)" if change_pct is not None else "n/a"
        formatted = f"{symbol.upper()}: ${price:,.2f} USD ({change_str})"
        return {
            "ok": True,
            "context": formatted,
            "formatted": formatted,
            "title": f"{symbol.upper()} Price",
            "url": f"https://www.coingecko.com/en/coins/{coin_id}",
            "provider": "finance",
            "source": "CoinGecko",
            "symbol": symbol.upper(),
            "price": price,
            "currency": "USD",
            "class": "finance_quote",
        }
    except Exception as e:
        logger.warning(f"CoinGecko fetch failed for {symbol}: {e}")
    return None


def _extract_price_from_snippets(results: list[dict]) -> tuple[str | None, str | None, str | None]:
    """Try to find a price-like number and currency in search snippets.

    Returns (price, source_name, url) or (None, None, None).
    """
    for result in results:
        snippet = (result.get("snippet", "") or "").strip()
        title = (result.get("title", "") or "").strip()
        url = (result.get("url", "") or "").strip()
        if not snippet:
            continue
        # Look for patterns like "$123.45", "123.45 USD", "Price 123.45"
        match = re.search(
            r"(?:price|closing|open)\s*:?\s*[$\u20ac\u00a3\u00a5]?\s*(\d{1,6}(?:,\d{3})*\.\d{2})\b",
            snippet,
            re.IGNORECASE,
        )
        if not match:
            match = re.search(r"[$\u20ac\u00a3\u00a5]\s*(\d{1,6}(?:,\d{3})*\.\d{2})\b", snippet)
        if match:
            return match.group(1), title, url
    return None, None, None


async def _search_web(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    """Run a web search via direct import, preserving the 20s timeout."""
    try:
        if str(ROOT_DIR) not in sys.path:
            sys.path.insert(0, str(ROOT_DIR))
        from tools.internet.search_web import multi_backend_search

        loop = asyncio.get_event_loop()
        backend, results = await asyncio.wait_for(
            loop.run_in_executor(None, multi_backend_search, query, max_results),
            timeout=20.0,
        )
        return results[:max_results]
    except Exception as e:
        logger.debug(f"Web search failed: {e}")
        return []


async def _fetch_stock_via_search(symbol: str) -> dict[str, Any] | None:
    """Fallback stock quote via web search when Yahoo Finance rate-limits.

    Search snippets rarely contain real-time prices. If a numeric price is
    found we return it with a freshness caveat; otherwise we return an honest
    unavailable message instead of a useless generic snippet.
    """
    query = f"{symbol} stock price"
    try:
        results = await _search_web(query, max_results=5)
        if not results:
            return None

        price, title, url = _extract_price_from_snippets(results)
        if price:
            formatted = (
                f"{symbol}: ~{price} USD (extracted from web search; "
                f"may be delayed or stale).\n\nSource: {title}\n{url}"
            )
            return {
                "ok": True,
                "context": formatted,
                "formatted": formatted,
                "title": f"{symbol} Quote",
                "url": url,
                "provider": "finance",
                "source": "web search (delayed)",
                "symbol": symbol,
                "class": "finance_quote",
            }

        # No price found: return an honest unavailable message.
        formatted = (
            f"Yahoo Finance is temporarily rate-limited and the web search fallback "
            f"did not return a current {symbol} price. Please try again in a minute."
        )
        return {
            "ok": True,
            "context": formatted,
            "formatted": formatted,
            "title": f"{symbol} Quote Unavailable",
            "url": "",
            "provider": "finance",
            "source": "yahoo finance rate-limited",
            "symbol": symbol,
            "class": "finance_quote_unavailable",
        }
    except Exception as e:
        logger.warning(f"Stock search fallback failed for {symbol}: {e}")
    return None


async def _fetch_net_worth(person: str) -> dict[str, Any] | None:
    """Fetch net-worth estimate via web search restricted to trusted finance sources."""
    query = f"{person} net worth"
    try:
        results = await _search_web(query, max_results=5)
        if not results:
            return None
        # Use the first result's snippet as evidence; include source URL
        top = results[0]
        snippet = top.get("snippet", "").strip()
        title = top.get("title", "")
        url = top.get("url", "")
        if not snippet:
            return None
        formatted = f"{person} net worth (from search): {snippet}\n\nSource: {title}\n{url}"
        return {
            "ok": True,
            "context": formatted,
            "formatted": formatted,
            "title": f"{person} Net Worth",
            "url": url,
            "provider": "finance",
            "source": "web search",
            "person": person,
            "class": "finance_net_worth",
        }
    except Exception as e:
        logger.warning(f"Net-worth fetch failed for {person}: {e}")
    return None


async def fetch_finance_evidence(question: str) -> dict[str, Any] | None:
    """Fetch live finance/market data for a question.

    Tries, in order:
      1. Exchange-rate queries (e.g. "EUR to USD")
      2. Stock / index / crypto quotes (e.g. "Tesla stock price")
      3. Individual net-worth queries (e.g. "How much is Elon Musk worth?")

    Returns an evidence dict with a formatted answer and source citation,
    or None if no live data could be retrieved.
    """
    logger.debug(f"Fetching finance evidence for: {question[:50]}...")

    # 1. Exchange rate
    fx = _match_exchange_rate(question)
    if fx:
        result = _fetch_exchange_rate(fx["base"], fx["target"])
        if result:
            return _apply_evidence_freshness(result)

    # 2. Stock / index / crypto quote
    symbol = _extract_stock_symbol(question)
    if symbol:
        # Try CoinGecko first for known crypto
        result = _fetch_coingecko(symbol)
        if result:
            return _apply_evidence_freshness(result)
        # Then Yahoo Finance for stocks/indices
        result = _fetch_yahoo_finance(symbol)
        if result:
            return _apply_evidence_freshness(result)
        # Fallback to web search if Yahoo rate-limits
        result = await _fetch_stock_via_search(symbol)
        if result:
            return _apply_evidence_freshness(result)

    # 3. Net worth / billionaire query
    person = _extract_net_worth_person(question)
    if person:
        result = await _fetch_net_worth(person)
        if result:
            return _apply_evidence_freshness(result)

    logger.info(f"No finance fetcher matched question: {question[:50]}")
    return _local_with_caveat_fallback(question, reason="no_finance_fetcher_matched")
