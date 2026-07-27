#!/usr/bin/env python3
"""Historical query detection."""

import re

# Pre-compiled historical query regexes for _is_historical_query
_YEAR_RE = re.compile(r"\b(1\d{3}|20\d{2})\b")
_UNAMBIGUOUS_HIST_RE = tuple(
    re.compile(p)
    for p in (
        r"\btreaty of\b",
        r"\bbattle of\b",
        r"\bwar in\b",
        r"\bwar of\b",
        r"\bthe fall of\b",
        r"\bthe rise of\b",
        r"\bwho won the .*\b(battle|war)\b",
        r"\bwho lost the .*\b(battle|war)\b",
        r"\bwho started the\b",
        r"\bwho (led|commanded|defeated) the\b",
        r"\bthe (black death|holocaust|renaissance|reformation|crusades)\b",
        r"\bin (ancient|medieval|colonial|victorian|roman|greek)\b",
        r"\bhistory of\b",
        r"\bhistorical\b",
    )
)
_HIST_PHRASES_RE = tuple(
    re.compile(p)
    for p in (
        r"\bwhat was the\b",
        r"\bwhat were the\b",
        r"\bwhat caused the\b",
        r"\bwhat happened during\b",
        r"\bwhat happened in\b",
        r"\bwho won\b",
        r"\bwho lost\b",
        r"\bhistory of\b",
        r"\bhistorical\b",
    )
)

def _is_historical_query(query: str) -> bool:
    """Detect whether a query is clearly about historical events.

    Historical queries should not trigger medical or financial evidence mode.
    Negation-aware: queries that explicitly negate history or use current-news
    markers are NOT treated as historical unless they contain an unambiguous
    historical anchor (year, "battle of", "treaty of", etc.).

    Examples:
        "What was the Treaty of Versailles?" -> True
        "What caused the Great Depression?" -> True
        "Not history - current Israeli news" -> False
        "Not historical, what is happening today in Gaza?" -> False
    """
    if not query:
        return False
    q = query.lower().strip()

    # Year patterns — 4-digit year between 1000-2999
    if _YEAR_RE.search(q):
        return True

    # Unambiguous historical anchors that override negation/current-news markers
    if any(p.search(q) for p in _UNAMBIGUOUS_HIST_RE):
        return True

    # Negation / current-news context: if the user explicitly negates history
    # or uses current-news markers, skip broad historical heuristics.
    current_news_markers = (
        "not history",
        "not historical",
        "current",
        "latest",
        "today",
        "news",
        "breaking",
        "recent",
    )
    if any(marker in q for marker in current_news_markers):
        return False

    # Remaining historical phrases (broad heuristics)
    if any(p.search(q) for p in _HIST_PHRASES_RE):
        return True

    return False
