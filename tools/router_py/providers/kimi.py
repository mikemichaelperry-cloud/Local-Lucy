"""Kimi provider caller."""

import json
import logging
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)
ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent


def _ensure_tools_path() -> None:
    tools_path = str(ROOT_DIR / "tools")
    if tools_path not in sys.path:
        sys.path.insert(0, tools_path)


def call_kimi_for_response(prompt: str, timeout: float = 130.0) -> str:
    """Call Kimi for direct response (sync version)."""
    try:
        _ensure_tools_path()
        import unverified_context_kimi as kimi_provider

        payload = kimi_provider.answer_question(prompt)
        if payload.get("ok"):
            return payload.get("text", payload.get("context", "No response"))
        error_detail = ""
        if isinstance(payload, dict) and not payload.get("ok"):
            error_detail = payload.get("reason", "")
        if not error_detail:
            error_detail = "Kimi provider failed"
        return f"Error: {error_detail}"
    except Exception as e:
        return f"Error calling Kimi: {e}"


def call_kimi_subprocess(question: str, timeout: float = 130.0) -> dict[str, Any] | None:
    """Call Kimi provider directly for evidence fetching."""
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
