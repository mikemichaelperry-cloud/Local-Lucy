#!/usr/bin/env python3
"""User-feedback logging for background learning."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .inference import _infer_corrected_route
from .memory import _retract_from_memory
from .types import FeedbackResult, FeedbackType


def log_user_feedback(result: FeedbackResult) -> bool:
    """Write a feedback result to user_feedback.jsonl for background_learner.

    Returns True if written successfully.
    """
    # Import these from the package so tests can monkey-patch fp.FEEDBACK_PATH.
    from feedback_parser import FEEDBACK_PATH, RUNTIME_NS

    try:
        # Determine the corrected route
        if result.corrected_route:
            correct_route = result.corrected_route
        elif result.feedback_type == FeedbackType.ANSWER_NEGATIVE:
            # Try to infer the correct route from exchange quality signals
            inferred = _infer_corrected_route(result)
            if inferred:
                correct_route = inferred
                result.corrected_route = inferred
                result.confidence = min(result.confidence, 0.7)
            else:
                return False
        elif result.feedback_type == FeedbackType.ANSWER_POSITIVE:
            # Confirmation: strengthen the existing route
            correct_route = result.original_route
        elif result.feedback_type == FeedbackType.RETRACTION:
            # Remove from memory if it was stored there
            _retract_from_memory(result.target_query)
            return True
        else:
            return False

        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "query": result.target_query,
            "correct_route": correct_route,
            "feedback_type": result.feedback_type.name.lower(),
            "original_route": result.original_route,
            "confidence": result.confidence,
            "raw_feedback": result.raw_text,
        }

        FEEDBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(FEEDBACK_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

        # Also write to runtime log for visibility
        log_path = RUNTIME_NS / "logs" / "feedback_log.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

        return True
    except Exception:
        return False
