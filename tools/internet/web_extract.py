#!/usr/bin/env python3
"""
Web extraction adapter for Local Lucy.

Tries webclaw (clean, structured extraction) first,
falls back to fetch gate + legacy HTMLParser-based extraction.

Usage:
    from web_extract import extract_webpage
    text = extract_webpage("https://medlineplus.gov/appendicitis.html", max_chars=2500)
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


# Simple noise lines — matched case-insensitively against stripped line content.
_NOISE_LINES: set[str] = {
    # MedlinePlus nav sections
    "see, play and learn",
    "research",
    "resources",
    "for you",
    "patient handouts",
    "find an expert",
    "statistics and research",
    "clinical trials",
    "journal articles",
    "children",
    "teenagers",
    # MedlinePlus bullets
    "no links available",
    # DailyMed / NIH
    "skip to main content",
    "national library of medicine",
    "report adverse events",
    "- loading image",
    "recalls",
    "dailymed announcements",
    "get rss news & updates",
    "about dailymed",
    "customer support",
    "safety reporting & recalls",
    "fda safety recalls",
    "fda resources",
    "nlm spl resources",
    "download data",
    "all drug labels",
    "all indexing & rems files",
    "all mapping files",
    "spl image guidelines",
    "articles & presentations",
    "application development support",
    "help",
    "all drugs",
    "human drugs",
    "animal drugs",
    "home",
    "news",
    # Merck Vet Manual
    "honeypot link",
    "skip to main content",
    "merck manual",
    "veterinary manual",
    "veterinary professionals",
    "pet owners",
    "resources",
    "quizzes",
    "about",
    "expand all",
    "collapse all",
    "<",
    # General
    "",
}


def _strip_site_noise(text: str) -> str:
    """Remove known navigation/header noise from extracted text.

    Handles site-specific patterns from MedlinePlus, DailyMed, Merck Vet Manual,
    and other common medical/veterinary sources.  Operates line-by-line and also
    strips consecutive bullet lines that follow a known nav section header.
    """
    if not text:
        return text

    lines = text.split("\n")
    kept: list[str] = []
    in_nav_section = False

    for line in lines:
        stripped = line.strip().lower()

        # Skip leading blank lines
        if not kept and not stripped:
            continue

        # Detect nav section headers (case-insensitive)
        if stripped in _NOISE_LINES:
            in_nav_section = True
            continue

        # If we're in a nav section, skip bullet lines and blank lines
        # until we hit non-bullet, non-blank content
        if in_nav_section:
            if stripped == "" or stripped.startswith("-") or stripped.startswith("•"):
                continue
            in_nav_section = False

        # Skip specific prefix patterns that aren't caught above
        if stripped.startswith("url of this page:"):
            continue
        if stripped.startswith("we're sorry."):
            continue
        if stripped.startswith("share sensitive information only on official"):
            continue
        if stripped.startswith("a lock (") and "https" in stripped:
            continue
        if stripped.startswith("secure .gov websites use https"):
            continue
        if stripped.startswith("official websites use .gov"):
            continue
        if stripped.startswith("dailymed - search results for"):
            continue

        kept.append(line)

    text = "\n".join(kept)
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


# Hard ceiling for fetched article content.
# The prompt builder truncates evidence to ~1200 chars, so fetching more
# than ~2.5× that wastes bandwidth and extraction time without benefit.
# This cap is applied regardless of what the caller requests.
MAX_EXTRACT_CHARS_HARD_CAP = int(os.environ.get("LUCY_WEB_EXTRACT_MAX_CHARS", "3000"))


def extract_webpage(
    url: str,
    *,
    max_chars: int = 2500,
    timeout: int = 20,
    prefer_webclaw: bool = True,
    _telemetry_out: dict[str, Any] | None = None,
) -> str | None:
    """
    Extract readable text from a web page.

    Args:
        url: The URL to fetch.
        max_chars: Maximum characters to return (truncates intelligently).
            Cannot exceed MAX_EXTRACT_CHARS_HARD_CAP (default 3000).
        timeout: Seconds to wait for fetch + extraction.
        prefer_webclaw: Try webclaw first if available.
        _telemetry_out: Optional dict populated with fallback telemetry.
            Keys: fallback_used, primary_failed, fallback_to, successful_backend,
            degradation_level.  For internal use only.

    Returns:
        Clean extracted text, or None if extraction failed.
    """
    # Enforce hard cap regardless of caller request
    effective_max = min(max_chars, MAX_EXTRACT_CHARS_HARD_CAP)

    text: str | None = None
    backend: str | None = None
    primary_failed: str = ""

    if prefer_webclaw:
        text = _extract_with_webclaw(url, timeout=timeout)
        if text is not None:
            backend = "webclaw"
        else:
            primary_failed = "webclaw"
    if text is None:
        text = _extract_with_fallback(url, timeout=timeout)
        if text is not None:
            backend = "legacy_html_parser"

    if text is None:
        if _telemetry_out is not None:
            _telemetry_out["fallback_used"] = primary_failed != ""
            _telemetry_out["primary_failed"] = primary_failed
            _telemetry_out["fallback_to"] = ""
            _telemetry_out["successful_backend"] = ""
            _telemetry_out["degradation_level"] = "low"
        return None

    text = _strip_toc_nav(text)
    text = _strip_site_noise(text)

    if _telemetry_out is not None:
        _telemetry_out["fallback_used"] = primary_failed != ""
        _telemetry_out["primary_failed"] = primary_failed
        _telemetry_out["fallback_to"] = "legacy_html_parser" if primary_failed else ""
        _telemetry_out["successful_backend"] = backend or ""
        _telemetry_out["degradation_level"] = "limited" if primary_failed else "none"

    return _truncate(text, effective_max)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Extract text from a web page")
    parser.add_argument("url", help="URL to extract")
    parser.add_argument("--max-chars", type=int, default=2500, help="Max characters to return")
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
