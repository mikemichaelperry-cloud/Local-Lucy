#!/usr/bin/env python3
"""Self-test entry point for the feedback_parser package."""

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(ROOT_DIR / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "tools"))

from router_py.feedback_buffer import get_buffer
from router_py.feedback_parser import parse_feedback, FeedbackType

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
