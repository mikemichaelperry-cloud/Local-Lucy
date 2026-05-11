"""OpenAI provider caller."""

import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)
ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent


def _prepare_subprocess_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Build isolated subprocess environment."""
    import os
    env = os.environ.copy()
    env["STATE_NAMESPACE_RAW"] = os.environ.get("LUCY_SHARED_STATE_NAMESPACE", "")
    if extra:
        env.update(extra)
    return env


def call_openai_for_response(prompt: str, timeout: float = 130.0) -> str:
    """Call OpenAI for direct response (sync version)."""
    tool = ROOT_DIR / "tools" / "unverified_context_openai.py"
    if not tool.exists():
        return "Error: OpenAI tool not found"
    try:
        result = subprocess.run(
            [sys.executable, str(tool), prompt],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_prepare_subprocess_env(),
            cwd=str(ROOT_DIR),
        )
        if result.returncode == 0:
            payload = json.loads(result.stdout)
            if payload.get("ok"):
                return payload.get("text", payload.get("context", "No response"))
        return f"Error: {result.stderr}"
    except Exception as e:
        return f"Error calling OpenAI: {e}"


def call_openai_subprocess(question: str, timeout: float = 130.0) -> dict[str, Any] | None:
    """Call OpenAI provider via subprocess for evidence fetching."""
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
