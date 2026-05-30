#!/usr/bin/env python3
"""
Web extraction adapter for Local Lucy.

Tries webclaw (clean, structured extraction) first,
falls back to fetch gate + legacy HTMLParser-based extraction.

Usage:
    from web_extract import extract_webpage
    text = extract_webpage("https://medlineplus.gov/appendicitis.html", max_chars=4000)
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

# Allow importing extract_text as fallback
_FALLBACK_DIR = Path(__file__).resolve().parent
if str(_FALLBACK_DIR) not in sys.path:
    sys.path.insert(0, str(_FALLBACK_DIR))


def _find_webclaw() -> Path | None:
    """Locate the webclaw binary."""
    # 1. Project-local bin/
    local = Path(__file__).resolve().parents[2] / "bin" / "webclaw"
    if local.exists() and os.access(local, os.X_OK):
        return local
    # 2. PATH
    path_bin = shutil.which("webclaw")
    if path_bin:
        return Path(path_bin)
    return None


def _truncate(text: str, max_chars: int) -> str:
    """Truncate text to max_chars, breaking at sentence boundary if possible."""
    if len(text) <= max_chars:
        return text
    # Try to break at sentence boundary
    truncated = text[:max_chars]
    m = re.search(r"[.!?]\s+", truncated[::-1])
    if m:
        idx = max_chars - m.end()
        return text[:idx].rstrip()
    # Fallback to word boundary
    idx = truncated.rfind(" ")
    if idx > max_chars * 0.8:
        return text[:idx].rstrip()
    return truncated.rstrip()


def _strip_toc_nav(text: str) -> str:
    """Remove 'On this page' table-of-contents blocks from extracted text."""
    # Strip the "On this page" nav block and its bullet list
    text = re.sub(
        r"\n\s*On this page\s*\n(?:[ \t]*[-–][^\n]*\n|[ \t]*[A-Z][a-zA-Z &]+\n|[ \t]*No [^\n]*available\n|\s*\n)*",
        "\n",
        text,
        flags=re.MULTILINE,
    )
    # Collapse excessive blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_with_webclaw(url: str, timeout: int = 20) -> str | None:
    """Use webclaw to extract clean text from a URL."""
    binary = _find_webclaw()
    if not binary:
        return None
    try:
        result = subprocess.run(
            [str(binary), url, "--format", "text", "--only-main-content", "--timeout", str(timeout)],
            capture_output=True,
            text=True,
            timeout=timeout + 5,
        )
        if result.returncode == 0:
            text = result.stdout.strip()
            # webclaw sometimes returns empty or just whitespace for some pages
            if text and len(text) > 100:
                return _strip_toc_nav(text)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return None


def _extract_with_fallback(url: str, timeout: int = 20) -> str | None:
    """Fallback: fetch via gate + legacy html_to_text."""
    root = Path(__file__).resolve().parents[2]
    gate = root / "tools" / "internet" / "run_fetch_with_gate.sh"
    if not gate.exists():
        return None
    try:
        result = subprocess.run(
            [str(gate), url],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            return None
        html = result.stdout
        if not html or len(html) < 200:
            return None
        # Use legacy extractor
        try:
            from extract_text import html_to_text
            text = html_to_text(html)
            if text and len(text) > 100:
                return text
        except Exception:
            return None
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return None


def extract_webpage(
    url: str,
    *,
    max_chars: int = 6000,
    timeout: int = 20,
    prefer_webclaw: bool = True,
) -> str | None:
    """
    Extract readable text from a web page.

    Args:
        url: The URL to fetch.
        max_chars: Maximum characters to return (truncates intelligently).
        timeout: Seconds to wait for fetch + extraction.
        prefer_webclaw: Try webclaw first if available.

    Returns:
        Clean extracted text, or None if extraction failed.
    """
    text: str | None = None
    if prefer_webclaw:
        text = _extract_with_webclaw(url, timeout=timeout)
    if text is None:
        text = _extract_with_fallback(url, timeout=timeout)
    if text is None:
        return None
    return _truncate(text, max_chars)


def extract_webpage_sync(
    url: str,
    *,
    max_chars: int = 6000,
    timeout: int = 20,
    prefer_webclaw: bool = True,
) -> str | None:
    """Alias for extract_webpage (always synchronous)."""
    return extract_webpage(url, max_chars=max_chars, timeout=timeout, prefer_webclaw=prefer_webclaw)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Extract text from a web page")
    parser.add_argument("url", help="URL to extract")
    parser.add_argument("--max-chars", type=int, default=6000, help="Max characters to return")
    parser.add_argument("--no-webclaw", action="store_true", help="Skip webclaw, use fallback only")
    args = parser.parse_args()

    result = extract_webpage(
        args.url,
        max_chars=args.max_chars,
        prefer_webclaw=not args.no_webclaw,
    )
    if result:
        print(result)
    else:
        print("ERROR: extraction failed", file=sys.stderr)
        sys.exit(1)
