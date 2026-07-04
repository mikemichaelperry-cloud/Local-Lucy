#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

try:
    from _env_loader import load_project_dotenv

    load_project_dotenv()
except Exception:
    pass


def _emit(payload: dict[str, Any], *, rc: int) -> int:
    print(json.dumps(payload))
    return rc


def _fail(reason: str) -> int:
    return _emit({"ok": False, "provider": "openai", "reason": reason}, rc=1)


def main() -> int:
    import sys

    question = " ".join(sys.argv[1:]).strip()
    if not question:
        return _fail("missing_question")

    mock_text = os.environ.get("LUCY_OPENAI_MOCK_TEXT", "").strip()
    mock_url = os.environ.get("LUCY_OPENAI_MOCK_URL", "").strip()
    if mock_text:
        return _emit(
            {
                "ok": True,
                "provider": "openai",
                "class": "openai_general",
                "url": mock_url,
                "text": re.sub(r"\s+", " ", mock_text).strip(),
            },
            rc=0,
        )

    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return _fail(
            "missing_openai_configuration: set OPENAI_API_KEY in lucy-v10/.env or environment"
        )

    api_base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").strip().rstrip("/")
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini").strip()
    if not api_base or not model:
        return _fail(
            "missing_openai_configuration: set OPENAI_BASE_URL/OPENAI_MODEL in lucy-v10/.env or environment"
        )

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    system_text = (
        "You are a factual research assistant. The user has been routed here because "
        "the question requires accurate, verifiable information. "
        "Answer as of the current date. Be concise but specific. "
        "Include approximate dates or timeframes when relevant. "
        "Cite your sources for every factual claim (e.g., 'According to Wikipedia...', 'Source: ...'). "
        "If you cannot verify a claim, omit it or say it is unknown. "
        "If you lack information beyond your training cutoff, say so directly. "
        "Do not invent facts, people, places, dates, or sources."
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
        with urllib.request.urlopen(request, timeout=5.0) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return _fail(f"openai_http_error_{e.code}")
    except urllib.error.URLError as e:
        return _fail(f"openai_network_error: {e.reason}")
    except Exception as e:
        return _fail(f"openai_request_failed: {e}")

    try:
        parsed = json.loads(raw)
    except Exception:
        return _fail("openai_bad_payload")

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
        return _fail("openai_no_text")

    return _emit(
        {
            "ok": True,
            "provider": "openai",
            "class": "openai_general",
            "url": "",
            "text": text,
        },
        rc=0,
    )


if __name__ == "__main__":
    raise SystemExit(main())
