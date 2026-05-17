#!/usr/bin/env python3
"""Kimi provider - Moonshot AI API integration."""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any


def _emit(payload: dict[str, Any], *, rc: int) -> int:
    print(json.dumps(payload))
    return rc


def _fail(reason: str) -> int:
    return _emit({"ok": False, "provider": "kimi", "reason": reason}, rc=1)


def main() -> int:
    import sys

    question = " ".join(sys.argv[1:]).strip()
    if not question:
        return _fail("missing_question")

    mock_text = os.environ.get("LUCY_KIMI_MOCK_TEXT", "").strip()
    mock_url = os.environ.get("LUCY_KIMI_MOCK_URL", "").strip()
    if mock_text:
        return _emit(
            {
                "ok": True,
                "provider": "kimi",
                "class": "kimi_general",
                "url": mock_url,
                "text": re.sub(r"\s+", " ", mock_text).strip(),
            },
            rc=0,
        )

    api_key = os.environ.get("KIMI_API_KEY", "").strip() or os.environ.get("MOONSHOT_API_KEY", "").strip()
    if not api_key:
        return _fail("missing_kimi_configuration")

    api_base = os.environ.get("KIMI_API_BASE_URL", "https://api.moonshot.ai/v1").strip().rstrip("/")
    model = os.environ.get("KIMI_MODEL", "moonshot-v1-8k").strip()
    if not api_base or not model:
        return _fail("missing_kimi_configuration")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    system_text = (
        "You are a current-events analyst. The user may ask about geopolitical, military, "
        "economic, or scientific developments. Answer as of the current date. "
        "If the topic involves rapidly changing events, explicitly note that situations evolve. "
        "Be concise but specific. Include approximate dates or timeframes when relevant. "
        "If you lack information beyond your training cutoff, say so directly."
    )
    user_text = f"Today is {now}.\n\n{question}"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_text},
            {"role": "user", "content": user_text},
        ],
        "temperature": 0.2,
    }
    request_body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{api_base}/chat/completions",
        data=request_body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=10.0) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return _fail(f"kimi_http_error_{e.code}")
    except urllib.error.URLError:
        return _fail("kimi_network_error")
    except Exception:
        return _fail("kimi_request_failed")

    try:
        parsed = json.loads(raw)
    except Exception:
        return _fail("kimi_bad_payload")

    text = ""
    if isinstance(parsed, dict):
        choices = parsed.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                msg = first.get("message")
                if isinstance(msg, dict):
                    text = str(msg.get("content", "")).strip()

    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return _fail("kimi_no_text")

    return _emit(
        {
            "ok": True,
            "provider": "kimi",
            "class": "kimi_general",
            "url": "",
            "text": text,
        },
        rc=0,
    )


if __name__ == "__main__":
    raise SystemExit(main())
