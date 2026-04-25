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


def _http_json(url: str, timeout: float = 2.5) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "LocalLucy/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8", errors="replace")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("expected JSON object")
    return parsed


def _normalize_query(query: str) -> str:
    normalized = re.sub(r"\s+", " ", (query or "").strip())
    normalized = re.sub(
        r"(?i)^(who was|who is|what is|what was|tell me about|give me an overview of|overview of|history of|explain)\s+",
        "",
        normalized,
        count=1,
    )
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

    try:
        try:
            direct_summary_url = "https://en.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(normalized_query, safe="")
            direct_summary_payload = _http_json(direct_summary_url)
            extract = _normalize_text(str(direct_summary_payload.get("extract", "")))
            canonical_url = str(((direct_summary_payload.get("content_urls") or {}).get("desktop") or {}).get("page", "")).strip()
            title = _normalize_text(str(direct_summary_payload.get("title", "")))
            if extract and title:
                payload = _success_payload(title=title, url=canonical_url, text=extract)
                _store_cached_payload(normalized_query, payload)
                return payload
        except Exception:
            pass

        search_url = (
            "https://en.wikipedia.org/w/api.php?action=query&format=json&list=search&srlimit=1&srsearch="
            + urllib.parse.quote(normalized_query, safe="")
        )
        search_payload = _http_json(search_url)
        search_items = (((search_payload.get("query") or {}).get("search")) or [])
        if not search_items:
            return {"ok": False}
        first = search_items[0] if isinstance(search_items[0], dict) else {}
        title = _normalize_text(str(first.get("title", "")))
        if not title:
            return {"ok": False}

        summary_url = "https://en.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(title, safe="")
        summary_payload = _http_json(summary_url)
        extract = _normalize_text(str(summary_payload.get("extract", "")))
        canonical_url = str(((summary_payload.get("content_urls") or {}).get("desktop") or {}).get("page", "")).strip()
        if not extract:
            return {"ok": False}

        payload = _success_payload(title=title, url=canonical_url, text=extract)
        _store_cached_payload(normalized_query, payload)
        return payload
    except Exception:
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
