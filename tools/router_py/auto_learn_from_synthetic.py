#!/usr/bin/env python3
"""Auto-learn from synthetic adversarial test failures.

Runs all synthetic cases through the router, logs feedback for mismatches,
triggers background learning, and rebuilds the embedding index.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "models" / "router"))

from router_py.classify import classify_intent, select_route
from background_learner import learn_once, FEEDBACK_PATH, is_learning_enabled

def main():
    cases_path = Path(__file__).parent.parent.parent / "tests" / "synthetic_adversarial_cases.jsonl"
    if not cases_path.exists():
        print(f"Cases file not found: {cases_path}")
        sys.exit(1)

    # Ensure auto-learning is enabled
    if not is_learning_enabled():
        print("Auto-learning is disabled. Remove .learner_disable or set LUCY_AUTO_LEARN=1")
        sys.exit(1)

    mismatches = []
    with open(cases_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            case = json.loads(line)
            query = case["prompt"]
            expected = case.get("expected_route")
            if not expected:
                continue

            classification = classify_intent(query)
            decision = select_route(classification, policy="fallback_only", query=query)
            actual = decision.route

            if actual != expected:
                mismatches.append({
                    "id": case["id"],
                    "query": query,
                    "expected": expected,
                    "actual": actual,
                    "family": case.get("family", ""),
                })

    print(f"Total mismatches: {len(mismatches)}")
    for m in mismatches:
        print(f"  {m['id']} ({m['family']}): '{m['query'][:60]}...' -> expected {m['expected']}, got {m['actual']}")

    if not mismatches:
        print("No mismatches to learn from.")
        return

    # Write feedback entries
    FEEDBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(FEEDBACK_PATH, "a", encoding="utf-8") as f:
        for m in mismatches:
            entry = {
                "timestamp": "2026-05-18T00:00:00Z",
                "query": m["query"],
                "correct_route": m["expected"],
                "feedback_type": "synthetic_adversarial_correction",
                "case_id": m["id"],
                "family": m["family"],
                "original_route": m["actual"],
            }
            f.write(json.dumps(entry) + "\n")

    print(f"\nWrote {len(mismatches)} feedback entries to {FEEDBACK_PATH}")

    # Trigger learning
    print("\nTriggering background learning...")
    result = learn_once(verbose=True)
    print(f"\nLearning result: {result}")

    # Re-test mismatches
    print("\nRe-testing mismatches after learning...")
    still_wrong = 0
    fixed = 0
    for m in mismatches:
        classification = classify_intent(m["query"])
        decision = select_route(classification, policy="fallback_only", query=m["query"])
        if decision.route == m["expected"]:
            fixed += 1
            print(f"  FIXED {m['id']}: {m['query'][:60]}... -> {decision.route}")
        else:
            still_wrong += 1
            print(f"  STILL {m['id']}: {m['query'][:60]}... -> expected {m['expected']}, got {decision.route}")

    print(f"\nFixed: {fixed}/{len(mismatches)}  Still wrong: {still_wrong}/{len(mismatches)}")

if __name__ == "__main__":
    main()
