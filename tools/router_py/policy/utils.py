#!/usr/bin/env python3
"""Policy utility helpers."""

import re


def _phrase_in_text(phrase: str, text: str) -> bool:
    """Return True when *phrase* appears as a distinct phrase in *text*.

    Uses word boundaries so short medical keywords such as "cut", "flu", or
    "operation" do not match inside unrelated words like "execution",
    "influence", or "operational". Multi-word phrases are matched as-is.
    """
    if not phrase or not text:
        return False
    pattern = r"\b" + re.escape(phrase) + r"\b"
    return bool(re.search(pattern, text))


# ---------------------------------------------------------------------------
# Module-level compiled regexes — avoids recompiling on every policy call
# ---------------------------------------------------------------------------
