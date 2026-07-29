#!/usr/bin/env python3
"""Feedback type definitions for Local Lucy."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional


class FeedbackType(Enum):
    ROUTE_CORRECTION = auto()
    ANSWER_NEGATIVE = auto()
    ANSWER_POSITIVE = auto()
    RETRACTION = auto()
    UNKNOWN = auto()


@dataclass
class FeedbackResult:
    """Result of parsing a potential feedback utterance."""

    feedback_type: FeedbackType
    target_query: str
    original_route: str
    corrected_route: Optional[str] = None
    confidence: float = 1.0
    raw_text: str = ""

    @property
    def is_correction(self) -> bool:
        return self.feedback_type in (
            FeedbackType.ROUTE_CORRECTION,
            FeedbackType.ANSWER_NEGATIVE,
        )

    @property
    def is_positive(self) -> bool:
        return self.feedback_type == FeedbackType.ANSWER_POSITIVE

    @property
    def is_retraction(self) -> bool:
        return self.feedback_type == FeedbackType.RETRACTION
