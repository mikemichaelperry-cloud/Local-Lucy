#!/usr/bin/env python3
"""Configuration constants for escalation suggestions."""

from __future__ import annotations

# Categories for which escalation must never be suggested, even when the
# suggest_web_escalation capability flag is enabled. These topics require
# trusted sources or local handling rather than open web search.
CRITICAL_CATEGORIES: tuple[str, ...] = (
    "medical",
    "financial",
    "finance",
    "market",
    "economic",
    "legal",
    "regulatory",
    "safety",
    "identity",
    "travel_advisory",
)

# Human-readable escalation suggestions. Keep them conservative: they invite
# the user to enable web search rather than performing escalation automatically.
SUGGESTION_GENERAL_KNOWLEDGE: str = "Enable web search for more sources."
SUGGESTION_CURRENT_INFO: str = "Enable web search for current information."

# Confidence threshold below which a LOCAL answer is considered "thin" and may
# trigger an escalation suggestion or an automatic general-knowledge web fetch.
# A value of 0.5 means "less than even chance"; it catches genuinely uncertain
# classifier output without flagging borderline-but-reasonable local answers.
THIN_LOCAL_CONFIDENCE_THRESHOLD: float = 0.5
