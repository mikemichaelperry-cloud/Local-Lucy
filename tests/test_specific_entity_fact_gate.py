#!/usr/bin/env python3
"""Condensed validation suite for the truth-first policy gates.

This test is intentionally small and fast (no model loading). It verifies that
factual queries about named real-world entities and broad factual lookups are
routed to AUGMENTED while personal, creative, and local-capability questions stay
out of the gates.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure imports resolve from repo root.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from router_py.policy_router import PolicyRouter  # noqa: E402


class MinimalClassification:
    """Stub ClassificationResult for policy-router tests."""

    evidence_mode = "not_required"
    evidence_reason = ""


ROUTER = PolicyRouter()


# Expected (route, reason_code) for each query.  Route None means no policy gate
# matched, so the embedding router would decide.
GATE_CASES = [
    # Specific named-entity facts -> AUGMENTED
    ("Tell me about Kibbutz Magal.", "AUGMENTED", "policy:specific_entity_fact"),
    ("actual facts about Kibbutz Magal", "AUGMENTED", "policy:specific_entity_fact"),
    (
        "Continue the story, but not a generic Kibbutz Magal, us actual facts about Kibbutz Magal.",
        "AUGMENTED",
        "policy:specific_entity_fact",
    ),
    ("Where is the Eiffel Tower?", "AUGMENTED", "policy:specific_entity_fact"),
    ("When was IBM founded?", "AUGMENTED", "policy:specific_entity_fact"),
    # Stable historical/scientific facts now stay LOCAL under the v11
    # stable-knowledge gate. Named entities that are not stable textbook facts
    # still route to AUGMENTED for verification.
    ("Who is Ada Lovelace?", "LOCAL", "policy:stable_knowledge"),
    ("History of the Roman Empire", "LOCAL", "policy:stable_knowledge"),
    # Broad factual lookups -> AUGMENTED (unless they are stable science or
    # historical war/conflict queries, which the embedding router handles locally).
    ("What is the capital of France?", "AUGMENTED", "policy:factual_lookup"),
    ("Why is the sky blue?", "AUGMENTED", "policy:factual_lookup"),
    ("How tall is Mount Everest?", "AUGMENTED", "policy:factual_lookup"),
    ("When did World War II end?", None, ""),
    ("What is photosynthesis?", "LOCAL", "policy:stable_knowledge"),
    # Local capabilities / exclusions
    ("Can you translate hello to French?", None, ""),
    ("How do I install Python?", None, ""),
    ("What is 2+2?", None, ""),
    ("Write a story about Kibbutz Magal.", None, ""),
    ("What is your opinion on AI?", "LOCAL", "policy:local_reasoning"),
    ("My dog likes to play.", "LOCAL", "policy:personal_family"),
    ("Who are you?", None, ""),
    ("What's up?", None, ""),
]


def _gate_result(query: str):
    decision = ROUTER.apply(query, MinimalClassification(), None)
    if decision is None:
        return None, ""
    return decision.route, decision.reason_code


def test_truth_first_gates() -> None:
    failures = []
    for query, expected_route, expected_reason in GATE_CASES:
        route, reason = _gate_result(query)
        if route != expected_route or reason != expected_reason:
            failures.append((query, expected_route, expected_reason, route, reason))

    if failures:
        print("FAILURES:")
        for query, exp_route, exp_reason, act_route, act_reason in failures:
            print(f"  {query!r}: expected {exp_route}/{exp_reason}, got {act_route}/{act_reason}")
        raise AssertionError(f"{len(failures)} policy-gate case(s) failed")

    total = len(GATE_CASES)
    print(f"PASS: {total}/{total} truth-first policy-gate cases passed")


if __name__ == "__main__":
    test_truth_first_gates()
