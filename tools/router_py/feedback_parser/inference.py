#!/usr/bin/env python3
"""Route-inference logic from failed or misrouted exchanges."""

from __future__ import annotations

from typing import Optional

try:
    from ..feedback_buffer import get_buffer
except ImportError:
    from feedback_buffer import get_buffer

from .patterns import (
    AUGMENTED_FAILURE_PATTERNS,
    LOCAL_FINANCIAL_DISCLAIMER_PATTERNS,
    LOCAL_LEGAL_DISCLAIMER_PATTERNS,
    LOCAL_MEDICAL_DISCLAIMER_PATTERNS,
    NEWS_FAILURE_PATTERNS,
    TIME_FAILURE_PATTERNS,
    WEATHER_FAILURE_PATTERNS,
    _FINANCIAL_KEYWORDS,
    _LEGAL_KEYWORDS,
    _MEDICAL_KEYWORDS,
    _NEWS_KEYWORDS,
    _TIME_KEYWORDS,
    _WEATHER_KEYWORDS,
    _has_pattern,
)
from .types import FeedbackResult


def _infer_corrected_route(result: FeedbackResult) -> Optional[str]:
    """Infer the correct route from the last exchange when user says 'wrong' generically.

    Returns a route name (e.g. 'LOCAL', 'AUGMENTED') or None if inference is unsafe.
    """
    buf = get_buffer()
    last_ex = buf.last()
    if last_ex is None:
        return None

    original_route = (last_ex.route or "").upper()
    query = (last_ex.query or "").strip()
    response = (last_ex.response_text or "").strip()
    response_lower = response.lower()

    if not query or not response:
        return None

    # Safety: don't infer for creative writing (LOCAL is correct)
    if last_ex.intent_family in ("local_answer", "creative_writing"):
        # Only infer if there's a clear provider failure
        pass  # fall through to failure checks

    # Safety: low-confidence original route
    if last_ex.confidence < 0.5:
        return None

    # 1. AUGMENTED → LOCAL: provider failure, admission of ignorance, or empty
    if original_route == "AUGMENTED":
        if _has_pattern(response, AUGMENTED_FAILURE_PATTERNS):
            return "LOCAL"
        if len(response) < 20:
            return "LOCAL"

    # 2. LOCAL → AUGMENTED: medical/financial/legal disclaimers
    if original_route == "LOCAL":
        query_lower = query.lower()
        if any(kw in query_lower for kw in _MEDICAL_KEYWORDS) and _has_pattern(
            response, LOCAL_MEDICAL_DISCLAIMER_PATTERNS
        ):
            return "AUGMENTED"
        if any(kw in query_lower for kw in _FINANCIAL_KEYWORDS) and _has_pattern(
            response, LOCAL_FINANCIAL_DISCLAIMER_PATTERNS
        ):
            return "AUGMENTED"
        if any(kw in query_lower for kw in _LEGAL_KEYWORDS) and _has_pattern(
            response, LOCAL_LEGAL_DISCLAIMER_PATTERNS
        ):
            return "AUGMENTED"

    # 3. TIME → LOCAL: timezone API failed OR semantic misroute
    if original_route == "TIME":
        if _has_pattern(response, TIME_FAILURE_PATTERNS):
            return "LOCAL"
        # Semantic misroute: query has no time keywords → should never have been TIME
        query_lower = query.lower()
        if not any(kw in query_lower for kw in _TIME_KEYWORDS):
            return "LOCAL"

    # 4. NEWS → LOCAL: news fetch failed OR semantic misroute
    if original_route == "NEWS":
        if _has_pattern(response, NEWS_FAILURE_PATTERNS):
            return "LOCAL"
        query_lower = query.lower()
        if not any(kw in query_lower for kw in _NEWS_KEYWORDS):
            return "LOCAL"

    # 5. WEATHER → LOCAL: weather fetch failed OR semantic misroute
    if original_route == "WEATHER":
        if _has_pattern(response, WEATHER_FAILURE_PATTERNS):
            return "LOCAL"
        query_lower = query.lower()
        if not any(kw in query_lower for kw in _WEATHER_KEYWORDS):
            return "LOCAL"

    return None
