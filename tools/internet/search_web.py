#!/usr/bin/env python3
"""Multi-backend web search for Local Lucy v10.

Backends (in priority order):
  1. duckduckgo      — Direct DuckDuckGo (free, no API key) ← PRIMARY
  2. searxng_json    — Local SearXNG JSON API
  3. searxng_html    — Local SearXNG HTML scrape fallback
  4. brave           — Brave Search API (requires LUCY_BRAVE_API_KEY)

Env:
  LUCY_SEARCH_BACKEND_PRIORITY — comma-separated backend list
                                 default: "duckduckgo,searxng_json,searxng_html,brave"
  LUCY_BRAVE_API_KEY           — Brave Search API key (free tier: 2,000 q/month)
  LUCY_SEARCH_ALLOWLIST_FILTER_FILE — optional domain filter file
  LUCY_AUDIT_LOG               — audit log path
  LUCY_ROOT                    — project root
"""

import hashlib
import json
import os
import re
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from html import unescape

try:
    from tools.internet.circuit_breaker import CircuitBreaker
except ImportError:
    # Fallback when run as standalone script without PYTHONPATH set
    _cb_path = os.path.join(os.path.dirname(__file__), "circuit_breaker.py")
    if os.path.exists(_cb_path):
        import importlib.util

        _spec = importlib.util.spec_from_file_location("circuit_breaker", _cb_path)
        _cb_mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_cb_mod)
        CircuitBreaker = _cb_mod.CircuitBreaker
    else:
        # Stub if circuit_breaker.py is missing
        class CircuitBreaker:
            def is_open(self, _):
                return False

            def record_success(self, _):
                pass

            def record_failure(self, _):
                pass


_SEARCH_CB = CircuitBreaker(failure_threshold=3, cooldown_sec=300)

TOOL_VERSION = 2

# ---------------------------------------------------------------------------
# TTL cache for search results (avoids repeated API calls for same query)
# ---------------------------------------------------------------------------
_SEARCH_CACHE: dict[str, tuple[list, float]] = {}
_SEARCH_CACHE_LOCK = threading.Lock()
_SEARCH_CACHE_TTL_SEC = 300  # 5 minutes


def _cache_key(query: str, backend: str, max_results: int) -> str:
    return hashlib.sha256(f"{backend}:{max_results}:{query}".encode()).hexdigest()


def _get_cached(query: str, backend: str, max_results: int) -> list | None:
    key = _cache_key(query, backend, max_results)
    with _SEARCH_CACHE_LOCK:
        entry = _SEARCH_CACHE.get(key)
        if entry is not None:
            results, cached_at = entry
            if time.time() - cached_at < _SEARCH_CACHE_TTL_SEC:
                return results
            del _SEARCH_CACHE[key]
    return None


def _set_cached(query: str, backend: str, max_results: int, results: list) -> None:
    key = _cache_key(query, backend, max_results)
    with _SEARCH_CACHE_LOCK:
        _SEARCH_CACHE[key] = (results, time.time())


SEARXNG_HTML_URL = "http://127.0.0.1:8080/search"
SEARXNG_JSON_URL = "http://127.0.0.1:8080/search?format=json"
SEARXNG_HEALTH_URL = "http://127.0.0.1:8080/"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"


def _searxng_is_healthy() -> bool:
    """Lightweight health probe for local SearXNG instance."""
    try:
        req = urllib.request.Request(SEARXNG_HEALTH_URL, method="GET", headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


def default_root() -> str:
    env_root = (os.environ.get("LUCY_ROOT") or "").strip()
    if env_root:
        return env_root
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def audit_log_path() -> str:
    env_path = (os.environ.get("LUCY_AUDIT_LOG") or "").strip()
    if env_path:
        return env_path
    return os.path.join(default_root(), "audit", "internet.log")


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def now_utc_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def append_audit(entry: dict) -> None:
    path = audit_log_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def clamp(n: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, n))


def domain_allowed(url: str, domains):
    if not domains:
        return True
    m = re.match(r"^https?://([^/]+)/", url)
    if not m:
        return False
    host = m.group(1).lower()
    for d in domains:
        d = str(d).lower().strip()
        if host == d or host.endswith("." + d):
            return True
    return False


def load_domains_from_file(path: str):
    doms = []
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            s = line.strip().lower()
            if not s or s.startswith("#"):
                continue
            doms.append(s)
    return doms


def strip_tags(s: str) -> str:
    s = re.sub(r"<script.*?</script>", " ", s, flags=re.I | re.S)
    s = re.sub(r"<style.*?</style>", " ", s, flags=re.I | re.S)
    s = re.sub(r"<[^>]+>", " ", s)
    s = unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _categorize_error(exc: Exception) -> str:
    """Categorize a backend exception into a human-readable string for telemetry."""
    if isinstance(exc, urllib.error.HTTPError):
        code = exc.code
        if code == 429:
            return f"rate_limited: HTTP {code}"
        elif code == 403:
            return f"blocked: HTTP {code}"
        elif code >= 500:
            return f"server_error: HTTP {code}"
        else:
            return f"http_error: HTTP {code}"
    elif isinstance(exc, urllib.error.URLError):
        reason = exc.reason
        if isinstance(reason, ConnectionRefusedError):
            return "connection_refused: SearXNG container not running"
        elif isinstance(reason, socket.timeout):
            return "timeout: request timed out"
        else:
            return f"network_error: {reason}"
    elif isinstance(exc, socket.timeout):
        return "timeout: request timed out"
    elif isinstance(exc, RuntimeError):
        return f"runtime_error: {exc}"
    else:
        return f"unknown: {exc}"


# ---------------------------------------------------------------------------
# Backend implementations
# ---------------------------------------------------------------------------


def searxng_search_json(query: str, max_results: int):
    """Search via SearXNG JSON API."""
    params = {"q": query}
    url = SEARXNG_JSON_URL + "&" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "X-Forwarded-For": "127.0.0.1",
            "X-Real-IP": "127.0.0.1",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8", errors="replace"))
    results = []
    for item in data.get("results", []):
        url2 = item.get("url", "").strip()
        title = item.get("title", "").strip()
        snippet = item.get("content", "").strip()
        if title and url2:
            results.append({"title": title, "url": url2, "snippet": snippet})
        if len(results) >= max_results:
            break
    return results


def searxng_search_html(query: str, max_results: int):
    """Search via SearXNG HTML scrape."""
    params = {"q": query}
    url = SEARXNG_HTML_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "X-Forwarded-For": "127.0.0.1",
            "X-Real-IP": "127.0.0.1",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        html = resp.read().decode("utf-8", errors="replace")

    results = []
    blocks = re.split(r'(<article\b[^>]*class="[^"]*\bresult\b[^"]*"[^>]*>)', html, flags=re.I)
    if len(blocks) > 1:
        articles = []
        for i in range(1, len(blocks), 2):
            articles.append(blocks[i] + (blocks[i + 1] if i + 1 < len(blocks) else ""))
    else:
        articles = re.split(r'(<div\b[^>]*class="[^"]*\bresult\b[^"]*"[^>]*>)', html, flags=re.I)
        if len(articles) > 1:
            tmp = []
            for i in range(1, len(articles), 2):
                tmp.append(articles[i] + (articles[i + 1] if i + 1 < len(articles) else ""))
            articles = tmp
        else:
            articles = [html]

    for a in articles:
        m = re.search(r'href="(https?://[^"]+)"', a, flags=re.I)
        if not m:
            continue
        url2 = unescape(m.group(1))
        m2 = re.search(r'href="https?://[^"]+"[^>]*>(.*?)</a>', a, flags=re.I | re.S)
        title = strip_tags(m2.group(1)) if m2 else ""
        m3 = re.search(
            r'class="[^"]*\b(content|snippet)\b[^"]*"[^>]*>(.*?)</', a, flags=re.I | re.S
        )
        snippet = strip_tags(m3.group(2)) if m3 else ""
        if title and url2:
            results.append({"title": title, "url": url2, "snippet": snippet})
        if len(results) >= max_results:
            break
    return results


def duckduckgo_search(query: str, max_results: int):
    """Search via DuckDuckGo direct (free, no API key)."""
    try:
        from ddgs import DDGS
    except ImportError as exc:
        raise RuntimeError(f"ddgs not installed: {exc}")

    with DDGS() as ddgs:
        raw = list(ddgs.text(query, max_results=max_results * 2, region="wt-wt", safesearch="off"))

    results = []
    for item in raw:
        url = item.get("href", "").strip()
        title = item.get("title", "").strip()
        snippet = item.get("body", "").strip()
        if title and url:
            results.append({"title": title, "url": url, "snippet": snippet})
        if len(results) >= max_results:
            break
    return results


def brave_search(query: str, max_results: int):
    """Search via Brave Search API (requires LUCY_BRAVE_API_KEY)."""
    api_key = (os.environ.get("LUCY_BRAVE_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("LUCY_BRAVE_API_KEY not set")

    url = "https://api.search.brave.com/res/v1/web/search"
    params = {"q": query, "count": max_results * 2, "offset": 0}
    req = urllib.request.Request(
        f"{url}?{urllib.parse.urlencode(params)}",
        headers={
            "Accept": "application/json",
            "X-Subscription-Token": api_key,
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8", errors="replace"))

    results = []
    for item in data.get("web", {}).get("results", []):
        url2 = item.get("url", "").strip()
        title = item.get("title", "").strip()
        snippet = item.get("description", "").strip()
        if title and url2:
            results.append({"title": title, "url": url2, "snippet": snippet})
        if len(results) >= max_results:
            break
    return results


# ---------------------------------------------------------------------------
# Backend dispatcher
# ---------------------------------------------------------------------------

BACKENDS = {
    "searxng_json": searxng_search_json,
    "searxng_html": searxng_search_html,
    "duckduckgo": duckduckgo_search,
    "brave": brave_search,
}


def multi_backend_search(query: str, max_results: int):
    """Try backends in priority order until one succeeds. Uses TTL cache."""
    raw_order = (os.environ.get("LUCY_SEARCH_BACKEND_PRIORITY") or "").strip()
    if raw_order:
        order = [b.strip().lower() for b in raw_order.split(",") if b.strip()]
    else:
        order = ["duckduckgo", "searxng_json", "searxng_html", "brave"]

    for backend_name in order:
        cached = _get_cached(query, backend_name, max_results)
        if cached is not None:
            return backend_name, cached

    errors = {}
    searxng_in_order = any(b in ("searxng_json", "searxng_html") for b in order)
    if searxng_in_order and not _searxng_is_healthy():
        for b in order:
            if b in ("searxng_json", "searxng_html"):
                errors[b] = "connection_refused: SearXNG container not running"
        order = [b for b in order if b not in ("searxng_json", "searxng_html")]

    for backend_name in order:
        if _SEARCH_CB.is_open(backend_name):
            errors[backend_name] = "circuit_open: cooling down"
            continue
        func = BACKENDS.get(backend_name)
        if func is None:
            continue
        try:
            results = func(query, max_results=max_results * 2)
            if results:
                _SEARCH_CB.record_success(backend_name)
                _set_cached(query, backend_name, max_results, results)
                return backend_name, results
            errors[backend_name] = "empty_results"
        except Exception as exc:
            _SEARCH_CB.record_failure(backend_name)
            errors[backend_name] = _categorize_error(exc)

    raise RuntimeError(f"all_backends_failed: {errors}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    raw = ""
    try:
        if not sys.stdin.isatty():
            raw = sys.stdin.read()
    except Exception:
        raw = ""

    inp = {}
    if raw.strip():
        try:
            inp = json.loads(raw)
        except Exception:
            print(json.dumps({"error": "invalid_json_input"}))
            sys.exit(2)
    else:
        if len(sys.argv) >= 2 and sys.argv[1].strip():
            inp = {"query": sys.argv[1].strip()}
        else:
            print(json.dumps({"error": "missing_query"}))
            sys.exit(2)

    query = (inp.get("query") or "").strip()
    if not query:
        print(json.dumps({"error": "missing_query"}))
        sys.exit(2)
    if len(query) > 256:
        print(json.dumps({"error": "query_too_long"}))
        sys.exit(2)

    try:
        max_results = int(inp.get("max_results", 5))
    except Exception:
        max_results = 5
    max_results = clamp(max_results, 1, 10)

    domains = inp.get("domains", None)
    if domains is not None and not isinstance(domains, list):
        domains = None
    if isinstance(domains, list):
        domains = [str(d).strip().lower() for d in domains if str(d).strip()]

    env_domains_file = (os.environ.get("LUCY_SEARCH_ALLOWLIST_FILTER_FILE") or "").strip()
    env_domains = None
    if env_domains_file:
        try:
            env_domains = load_domains_from_file(env_domains_file)
        except Exception:
            print(
                json.dumps(
                    {"error": "invalid_domains_filter_file", "path": env_domains_file},
                    ensure_ascii=False,
                )
            )
            sys.exit(2)
        if not env_domains:
            print(
                json.dumps(
                    {"error": "empty_domains_filter_file", "path": env_domains_file},
                    ensure_ascii=False,
                )
            )
            sys.exit(2)

    effective_domains = domains
    if env_domains is not None:
        if effective_domains is None:
            effective_domains = env_domains
        else:
            effective_domains = [
                d
                for d in effective_domains
                if any(d == e or d.endswith("." + e) for e in env_domains)
            ]

    fetched_at = now_utc_iso()

    try:
        backend, results = multi_backend_search(query, max_results=max_results)
    except Exception as e:
        print(json.dumps({"error": "search_backend_failed", "detail": str(e)}, ensure_ascii=False))
        sys.exit(3)

    results = [r for r in results if domain_allowed(r["url"], effective_domains)]
    results = results[:max_results]

    out = {
        "results": results,
        "meta": {
            "fetched_at_utc": fetched_at,
            "tool_version": TOOL_VERSION,
            "backend": backend,
        },
    }

    out_json = json.dumps(out, ensure_ascii=False, sort_keys=True)
    out_hash = sha256_text(out_json)
    out["meta"]["output_sha256"] = out_hash

    append_audit(
        {
            "ts_utc": fetched_at,
            "tool": "search_web",
            "tool_version": TOOL_VERSION,
            "backend": backend,
            "inputs": {"query": query, "max_results": max_results, "domains": effective_domains},
            "output_sha256": out_hash,
        }
    )

    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
