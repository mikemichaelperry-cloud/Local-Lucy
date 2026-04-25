#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any


def _emit(payload: dict[str, Any], *, rc: int) -> int:
    print(json.dumps(payload))
    return rc


def _fail(reason: str) -> int:
    return _emit({"ok": False, "provider": "grok", "reason": reason}, rc=1)


def main() -> int:
    import sys

    question = " ".join(sys.argv[1:]).strip()
    if not question:
        return _fail("missing_question")

    mock_text = os.environ.get("LUCY_GROK_MOCK_TEXT", "").strip()
    mock_url = os.environ.get("LUCY_GROK_MOCK_URL", "").strip()
    if mock_text:
        return _emit(
            {
                "ok": True,
                "provider": "grok",
                "class": "grok_general",
                "url": mock_url,
                "text": re.sub(r"\s+", " ", mock_text).strip(),
            },
            rc=0,
        )

    api_key = os.environ.get("GROK_API_KEY", "").strip()
    if not api_key:
        return _fail("missing_grok_configuration")

    api_base = os.environ.get("GROK_API_BASE_URL", "https://api.x.ai/v1").strip().rstrip("/")
    model = os.environ.get("GROK_MODEL", "grok-2-latest").strip()
    if not api_base or not model:
        return _fail("missing_grok_configuration")

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Provide a concise, high-level background summary for a user question. "
                    "Do not claim verification, do not provide evidence citations, and keep under 120 words."
                ),
            },
            {
                "role": "user",
                "content": question,
            },
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
        with urllib.request.urlopen(request, timeout=5.0) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError:
        return _fail("grok_http_error")
    except urllib.error.URLError:
        return _fail("grok_network_error")
    except Exception:
        return _fail("grok_request_failed")

    try:
        parsed = json.loads(raw)
    except Exception:
        return _fail("grok_bad_payload")

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
        return _fail("grok_no_text")

    return _emit(
        {
            "ok": True,
            "provider": "grok",
            "class": "grok_general",
            "url": "",
            "text": text,
        },
        rc=0,
    )


if __name__ == "__main__":
    raise SystemExit(main())
