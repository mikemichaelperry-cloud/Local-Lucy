#!/usr/bin/env python3
"""Natural-language feedback parser."""

from __future__ import annotations

from typing import Optional

try:
    from ..feedback_buffer import get_buffer
except ImportError:
    from feedback_buffer import get_buffer

from .patterns import (
    ANSWER_NEGATIVE_PATTERNS,
    ANSWER_POSITIVE_PATTERNS,
    RETRACTION_PATTERNS,
    ROUTE_CORRECTION_PATTERNS,
    _extract_route,
    _matches_any,
)
from .types import FeedbackResult, FeedbackType


def parse_feedback(text: str) -> Optional[FeedbackResult]:
    """Parse a user utterance to detect feedback about a prior exchange.

    Returns None if the text does not appear to be feedback.
    """
    text_stripped = text.strip()
    if len(text_stripped) < 3:
        return None

    q_lower = text_stripped.lower()
    buf = get_buffer()
    last_ex = buf.last()

    # No prior exchange to attribute feedback to
    if last_ex is None:
        return None

    # --- 1. Route correction (most specific) ---
    if _matches_any(q_lower, ROUTE_CORRECTION_PATTERNS):
        corrected = _extract_route(text_stripped)
        # If they say "not LOCAL" without specifying what it IS, try to infer
        if corrected is None:
            # e.g. "that was wrong, not LOCAL" — we know original was LOCAL
            # but we don't know what it should be; fall through to generic negative
            pass
        else:
            return FeedbackResult(
                feedback_type=FeedbackType.ROUTE_CORRECTION,
                target_query=last_ex.query,
                original_route=last_ex.route,
                corrected_route=corrected,
                confidence=1.0,
                raw_text=text_stripped,
            )

    # --- 2. Retraction ---
    if _matches_any(q_lower, RETRACTION_PATTERNS):
        return FeedbackResult(
            feedback_type=FeedbackType.RETRACTION,
            target_query=last_ex.query,
            original_route=last_ex.route,
            confidence=1.0,
            raw_text=text_stripped,
        )

    # --- 3. Negative answer quality ---
    if _matches_any(q_lower, ANSWER_NEGATIVE_PATTERNS):
        return FeedbackResult(
            feedback_type=FeedbackType.ANSWER_NEGATIVE,
            target_query=last_ex.query,
            original_route=last_ex.route,
            confidence=0.8,
            raw_text=text_stripped,
        )

    # --- 4. Positive answer quality ---
    if _matches_any(q_lower, ANSWER_POSITIVE_PATTERNS):
        return FeedbackResult(
            feedback_type=FeedbackType.ANSWER_POSITIVE,
            target_query=last_ex.query,
            original_route=last_ex.route,
            confidence=0.8,
            raw_text=text_stripped,
        )

    return None
