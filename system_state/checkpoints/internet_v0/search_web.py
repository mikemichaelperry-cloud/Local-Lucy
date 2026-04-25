#!/usr/bin/env python3
import json
import sys
import time
import hashlib
import urllib.parse
import urllib.request
import re
from html import unescape

TOOL_VERSION = 0
AUDIT_LOG = "/home/mike/lucy/audit/internet.log"
SEARXNG_HTML_URL = "http://127.0.0.1:8080/search"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"

def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def now_utc_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

def append_audit(entry: dict) -> None:
    with open(AUDIT_LOG, "a", encoding="utf-8") as f:
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

def strip_tags(s: str) -> str:
    s = re.sub(r"<script.*?</script>", " ", s, flags=re.I|re.S)
    s = re.sub(r"<style.*?</style>", " ", s, flags=re.I|re.S)
    s = re.sub(r"<[^>]+>", " ", s)
    s = unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def searxng_search_html(query: str, max_results: int):
    params = {"q": query}
    url = SEARXNG_HTML_URL + "?" + urllib.parse.urlencode(params)

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            # Keep these: SearXNG botdetection sometimes wants an IP identity
            "X-Forwarded-For": "127.0.0.1",
            "X-Real-IP": "127.0.0.1",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        html = resp.read().decode("utf-8", errors="replace")

    # Heuristic parse:
    # SearXNG results typically appear as <article class="result ..."> ... <a ... href="URL">TITLE</a> ... <p class="content">SNIPPET</p>
    results = []
    # Split by article blocks if present
    blocks = re.split(r'(<article\b[^>]*class="[^"]*\bresult\b[^"]*"[^>]*>)', html, flags=re.I)
    if len(blocks) > 1:
        # recombine marker+content
        articles = []
        for i in range(1, len(blocks), 2):
            articles.append(blocks[i] + (blocks[i+1] if i+1 < len(blocks) else ""))
    else:
        # fallback: look for "result" divs
        articles = re.split(r'(<div\b[^>]*class="[^"]*\bresult\b[^"]*"[^>]*>)', html, flags=re.I)
        if len(articles) > 1:
            tmp = []
            for i in range(1, len(articles), 2):
                tmp.append(articles[i] + (articles[i+1] if i+1 < len(articles) else ""))
            articles = tmp
        else:
            articles = [html]

    for a in articles:
        # href
        m = re.search(r'href="(https?://[^"]+)"', a, flags=re.I)
        if not m:
            continue
        url2 = unescape(m.group(1))

        # title: first anchor text after href
        m2 = re.search(r'href="https?://[^"]+"[^>]*>(.*?)</a>', a, flags=re.I|re.S)
        title = strip_tags(m2.group(1)) if m2 else ""

        # snippet
        m3 = re.search(r'class="[^"]*\b(content|snippet)\b[^"]*"[^>]*>(.*?)</', a, flags=re.I|re.S)
        snippet = strip_tags(m3.group(2)) if m3 else ""

        if title and url2:
            results.append({"title": title, "url": url2, "snippet": snippet})
        if len(results) >= max_results:
            break

    return results

def main():
    # Tool protocol: prefer JSON on stdin, but allow argv fallback for scripts.
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
        # argv fallback: python3 search_web.py "query"
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

    fetched_at = now_utc_iso()

    try:
        results = searxng_search_html(query, max_results=max_results * 2)
    except Exception as e:
        print(json.dumps({"error": "search_backend_failed", "detail": str(e)}, ensure_ascii=False))
        sys.exit(3)

    results = [r for r in results if domain_allowed(r["url"], domains)]
    results = results[:max_results]

    out = {
        "results": results,
        "meta": {
            "fetched_at_utc": fetched_at,
            "tool_version": TOOL_VERSION,
            "backend": "searxng_localhost_html",
        }
    }

    out_json = json.dumps(out, ensure_ascii=False, sort_keys=True)
    out_hash = sha256_text(out_json)
    out["meta"]["output_sha256"] = out_hash

    append_audit({
        "ts_utc": fetched_at,
        "tool": "search_web",
        "tool_version": TOOL_VERSION,
        "backend": "searxng_localhost_html",
        "inputs": {"query": query, "max_results": max_results, "domains": domains},
        "output_sha256": out_hash,
    })

    print(json.dumps(out, ensure_ascii=False))

if __name__ == "__main__":
    main()
