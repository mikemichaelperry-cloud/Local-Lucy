#!/usr/bin/env python3
"""HMI-style routing smoke tests using the real classify+route pipeline.

No LLM inference is invoked; only the embedding router and policy guards run.
Tests cover the real HMI failure families plus adversarial/negative controls.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from router_py.pipeline import classify, route
from router_py.request_types import RouterOutcome

os.environ.setdefault("LUCY_EVIDENCE_ENABLED", "1")
os.environ.setdefault("LUCY_ENABLE_INTERNET", "1")


TEST_CASES = [
    # Real HMI restaurant failures
    ("Hi Lucy, whas a good restraunt near me that is open on Saturdays?", ["AUGMENTED", "EVIDENCE"], ["TIME", "WEATHER", "LOCAL"]),
    ("I live in Kibbutz Magal. Search for restraunts in my area that are open today.", ["AUGMENTED", "EVIDENCE"], ["TIME", "LOCAL"]),
    ("I am looking for a good restraunt open today near kibbutz Magal.", ["AUGMENTED", "EVIDENCE"], ["TIME", "WEATHER", "LOCAL"]),
    ("Can you please suggest a good restaurant in this area that is oppen on Saturdays?", ["AUGMENTED", "EVIDENCE"], ["LOCAL", "TIME", "WEATHER"]),
    ("How about in the Hadera area?", ["AUGMENTED", "EVIDENCE"], ["LOCAL"]),
    ("restaurants open now near me", ["AUGMENTED", "EVIDENCE"], ["TIME", "WEATHER", "LOCAL"]),
    # Search imperatives (no context available here, so bare ones should stay LOCAL)
    ("Use DuckDuckGo search", ["LOCAL", "CLARIFY"], ["AUGMENTED", "EVIDENCE", "NEWS"]),
    ("Can you search the web?", ["LOCAL"], ["AUGMENTED", "EVIDENCE", "NEWS"]),
    # Location facts
    ("Do you know where I live?", ["LOCAL"], ["AUGMENTED", "EVIDENCE", "NEWS"]),
    ("Actually I live in Kibbutz Magal in Israel.", ["LOCAL"], ["AUGMENTED", "EVIDENCE", "NEWS"]),
    # Adversarial / negative controls
    ("Find somewhere nearby, but do not search the web.", ["LOCAL"], ["AUGMENTED", "EVIDENCE", "NEWS"]),
    ("What is 2 + 2? Search the web.", ["LOCAL"], ["AUGMENTED", "EVIDENCE"]),
    ("restaurants near my daughter", ["LOCAL", "AUGMENTED"], []),
    ("The article says, 'I live in London.'", ["LOCAL"], []),
    ("I no longer live in Tel Aviv.", ["LOCAL"], []),
    ("What would the weather be like if I moved there?", ["LOCAL", "WEATHER", "AUGMENTED"], []),
    ("Can you browse the internet?", ["LOCAL"], ["AUGMENTED", "EVIDENCE", "NEWS"]),
    ("Who are you?", ["LOCAL"], ["AUGMENTED", "EVIDENCE", "NEWS"]),
    # Operational routes
    ("What's the weather in Hadera?", ["WEATHER"], ["LOCAL", "AUGMENTED"]),
    ("What time is it in Rome?", ["TIME"], ["LOCAL", "AUGMENTED"]),
    ("Current price of Apple stock", ["FINANCE", "AUGMENTED"], ["LOCAL"]),
    ("Latest news about Israel", ["NEWS"], ["LOCAL", "AUGMENTED"]),
    ("What is lisinopril?", ["EVIDENCE"], ["AUGMENTED", "LOCAL"]),
    ("My dog is vomiting after eating chocolate.", ["EVIDENCE"], ["AUGMENTED", "LOCAL"]),
]


def evaluate_case(query: str, acceptable: list[str], forbidden: list[str]) -> tuple[bool, str]:
    classify_result, _, _ = classify.classify_question(
        query, surface="cli", model=None, route_prefix="", context={}
    )
    if isinstance(classify_result, RouterOutcome):
        return False, f"classification_error:{classify_result.outcome_code}"

    decision_or_outcome = route.select_route_for_question(
        classify_result, query, policy="fallback_only", context={}
    )
    if hasattr(decision_or_outcome, "route"):
        predicted = decision_or_outcome.route
    else:
        return False, "no_route"

    if predicted in forbidden:
        return False, predicted
    if predicted in acceptable:
        return True, predicted
    return False, predicted


def main() -> int:
    passed = 0
    failed = 0
    results: list[dict] = []
    for query, acceptable, forbidden in TEST_CASES:
        ok, pred = evaluate_case(query, acceptable, forbidden)
        passed += int(ok)
        failed += int(not ok)
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {query!r} -> {pred} (acceptable={acceptable})")
        results.append({"query": query, "predicted": pred, "acceptable": acceptable, "forbidden": forbidden, "status": status})

    print(f"\nHMI routing smoke: {passed}/{len(TEST_CASES)} passed")
    output_path = Path(__file__).with_name("results") / "hmi_routing_smoke.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({"passed": passed, "total": len(TEST_CASES), "results": results}, f, indent=2)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
