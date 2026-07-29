#!/usr/bin/env python3
"""Natural-language feedback parser for Local Lucy.

Detects when the user is giving feedback about a prior response
(rather than asking a new question). Extracts corrections and
prepares them for the background learner.

Patterns detected:
  - Route corrections:  "that should have been LOCAL", "wrong route, it was NEWS"
  - Answer quality:     "that was wrong", "bad answer", "incorrect"
  - Positive feedback:  "that was right", "good answer", "perfect"
  - Retractions:        "forget that", "don't answer that", "ignore that"

Usage:
    from feedback_parser import parse_feedback, FeedbackType
    result = parse_feedback("that was wrong, it should have been LOCAL")
    if result:
        print(result.type, result.corrected_route, result.target_query)
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure tools package is importable when this package is loaded directly.
ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(ROOT_DIR / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "tools"))

from tools.xdg_paths import lucy_runtime_namespace_root

# Where to write user feedback for background_learner.py
RUNTIME_NS = lucy_runtime_namespace_root()
ROUTER_DIR = Path(__file__).resolve().parent.parent.parent.parent / "models" / "router"
FEEDBACK_PATH = ROUTER_DIR / "user_feedback.jsonl"

from .inference import _infer_corrected_route
from .learner import trigger_background_learning
from .logger import log_user_feedback
from .parser import parse_feedback
from .types import FeedbackResult, FeedbackType


def apply_feedback(
    text: str,
    confirmation_callback=None,
):
    """High-level entry: parse feedback, log it, trigger learning, optionally confirm.

    Args:
        text: The raw user utterance.
        confirmation_callback: Optional callable(text) for TTS confirmation.

    Returns:
        FeedbackResult if feedback was detected and handled, else None.
    """
    result = parse_feedback(text)
    if result is None:
        return None

    # Log the feedback
    logged = log_user_feedback(result)

    # Trigger background learning
    triggered = trigger_background_learning()

    # Confirmation message
    if result.feedback_type == FeedbackType.ROUTE_CORRECTION:
        msg = f"Got it. I'll remember that '{result.target_query[:40]}...' should route to {result.corrected_route}."
    elif result.feedback_type == FeedbackType.ANSWER_NEGATIVE:
        msg = "Noted. I'll work on improving that answer."
    elif result.feedback_type == FeedbackType.ANSWER_POSITIVE:
        msg = "Thanks for the feedback!"
    elif result.feedback_type == FeedbackType.RETRACTION:
        msg = "Okay, I've forgotten that."
    else:
        msg = "Noted."

    if confirmation_callback:
        confirmation_callback(msg)

    return result


__all__ = [
    "FeedbackType",
    "FeedbackResult",
    "parse_feedback",
    "log_user_feedback",
    "trigger_background_learning",
    "apply_feedback",
    "_infer_corrected_route",
    "FEEDBACK_PATH",
    "RUNTIME_NS",
]


if __name__ == "__main__":
    # Quick self-test — seed buffer with a prior exchange
    import sys
    from pathlib import Path

    ROOT_DIR = Path(__file__).resolve().parent.parent.parent
    if str(ROOT_DIR) not in sys.path:
        sys.path.insert(0, str(ROOT_DIR))
    if str(ROOT_DIR / "tools") not in sys.path:
        sys.path.insert(0, str(ROOT_DIR / "tools"))

    from feedback_buffer import get_buffer

    buf = get_buffer()
    buf.append("What is the weather in London?", "WEATHER", "ephemeral_query", "Sunny, 22C", 0.95)

    test_cases = [
        ("that was wrong, it should have been LOCAL", FeedbackType.ROUTE_CORRECTION),
        ("wrong route, that was NEWS", FeedbackType.ROUTE_CORRECTION),
        ("that was a bad answer", FeedbackType.ANSWER_NEGATIVE),
        ("perfect, thank you", FeedbackType.ANSWER_POSITIVE),
        ("forget that", FeedbackType.RETRACTION),
        ("what is the weather in London?", None),
    ]
    ok = 0
    for text, expected in test_cases:
        result = parse_feedback(text)
        detected = result.feedback_type if result else None
        status = "✅" if detected == expected else "❌"
        if detected == expected:
            ok += 1
        print(f"{status} {text!r:50s} → {detected}")
    print(f"\n{ok}/{len(test_cases)} tests passed")
