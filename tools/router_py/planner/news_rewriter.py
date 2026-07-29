#!/usr/bin/env python3
"""News query rewriting for the plan-to-pipeline CLI.

This module holds the query rewrite logic that used to live inline in
``plan_to_pipeline_cli.py``. It rewrites a user's question into an explicit
news-focused form when the router has selected the NEWS route.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Ensure tools package is importable when this module is loaded directly.
TOOLS_DIR = Path(__file__).resolve().parent.parent.parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))


def _has_re(text: str, pattern: str) -> bool:
    return re.search(pattern, text or "", flags=re.IGNORECASE) is not None


def rewrite_news_query(question: str) -> str:
    """Rewrite ``question`` into an explicit news query when appropriate.

    The rewrite is conservative: if the question already contains news
    terminology it is returned unchanged.
    """
    rewritten = (question or "").strip()
    if not rewritten or _has_re(rewritten, r"\b(news|headline|headlines|breaking)\b"):
        return rewritten
    if _has_re(rewritten, r"\bwhat happened in\b"):
        rewritten = re.sub(
            r"(?i)\bwhat happened in\b",
            "What are the latest news and developments in",
            rewritten,
            count=1,
        )
    elif _has_re(rewritten, r"\blatest developments?\b"):
        rewritten = re.sub(
            r"(?i)\blatest developments?\b", "latest news and developments", rewritten, count=1
        )
    elif _has_re(rewritten, r"\b(most significant|major|key)\s+developments?\b"):
        rewritten = re.sub(
            r"(?i)\b(most significant|major|key)\s+developments?\b",
            "latest news and developments",
            rewritten,
            count=1,
        )
    elif _has_re(rewritten, r"\blatest on\b"):
        rewritten = re.sub(
            r"(?i)\blatest on\b", "the latest news and developments on", rewritten, count=1
        )
    elif _has_re(rewritten, r"\b(today|latest|recent|right now|now)\b"):
        rewritten = rewritten.rstrip("?.! ")
        rewritten = f"{rewritten}. Focus on the latest news and developments."
    else:
        topic = rewritten.rstrip("?.! ")
        topic = re.sub(r"(?i)^\s*what\s+(?:are|is)\s+", "", topic).strip()
        topic = re.sub(r"(?i)^\s*(?:tell me|give me|summarize|update me on)\s+", "", topic).strip()
        if not topic:
            topic = rewritten.rstrip("?.! ")
        rewritten = f"What are the latest news and developments about {topic}?"
    if _has_re(rewritten, r"^what\b") and not rewritten.endswith("?"):
        rewritten = f"{rewritten}?"
    return rewritten
