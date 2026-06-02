#!/usr/bin/env python3
"""
Policy Hybrid Burn-in: Focused test for the MiniLM/keyword policy layer.

Tests the exact adversarial set plus boundary queries. No Ollama needed —
this exercises classify_intent → select_route → policy guards only.

Usage:
    cd /home/mike/lucy-v10
    PYTHONPATH=tools python tests/burn_in_policy_hybrid.py

Output:
    - Console summary table
    - router_decisions_policy_burnin.jsonl  (decision audit trail)
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Ensure router_py can be imported
sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

from router_py.classify import classify_intent, select_route
from router_py.policy import normalize_augmentation_policy

# Force Python-only path and enable decision logging
os.environ["LUCY_LOCAL_ANSWER_PY"] = "1"
os.environ["LUCY_DIRECT_EXECUTION"] = "1"
os.environ["LUCY_USE_SQLITE_STATE"] = "1"
os.environ["LUCY_ROUTER_LOG_DIR"] = str(Path(__file__).parent.parent / "burn_in_logs")


# ---------------------------------------------------------------------------
# Query test matrix
# ---------------------------------------------------------------------------

BURNIN_QUERIES = [
    # --- LOCAL: personal / family (must NOT trigger evidence) ---
    ("Who is my wife?", "LOCAL", "personal_family_context"),
    ("What is my dog's name?", "LOCAL", "personal_family_context"),
    ("Where is my cat?", "LOCAL", "personal_family_context"),
    ("How old is my daughter?", "LOCAL", "personal_family_context"),
    ("Do I have any children?", "LOCAL", "personal_family_context"),
    ("How many kids do I have?", "LOCAL", "personal_family_context"),
    ("Tell me about my son.", "LOCAL", "personal_family_context"),
    ("What is my daughter's name?", "LOCAL", "personal_family_context"),
    ("Is my cat hungry?", "LOCAL", "personal_family_context"),
    ("When did I get my dog?", "LOCAL", "personal_family_context"),

    # --- EVIDENCE: medical / vet with symptoms (MUST trigger evidence) ---
    ("My wife has chest pain.", "EVIDENCE", "medical_context"),
    ("My dog has diarrhea.", "EVIDENCE", "veterinary_context"),
    ("My cat is not eating.", "EVIDENCE", "veterinary_context"),
    ("My child has a fever.", "EVIDENCE", "medical_context"),
    ("My dog ate chocolate.", "EVIDENCE", "veterinary_context"),
    ("My daughter has a fever.", "EVIDENCE", "medical_context"),
    ("My dog has been vomiting.", "EVIDENCE", "veterinary_context"),
    ("My son is vomiting.", "EVIDENCE", "medical_context"),

    # --- LOCAL: normal non-health queries ---
    ("Hello", "LOCAL", "default_light"),
    ("What is the weather today?", "WEATHER", "weather_query"),
    ("Tell me about dinosaurs", "LOCAL", "default_light"),
    ("How does photosynthesis work?", "LOCAL", "default_light"),
    ("Who was Ada Lovelace?", "LOCAL", "default_light"),
    ("What is 2+2?", "LOCAL", "default_light"),
    ("Explain quantum mechanics", "LOCAL", "default_light"),
    ("Recipe for chocolate cake", "LOCAL", "default_light"),

    # --- EVIDENCE: medical without family subject ---
    ("What are the symptoms of flu?", "EVIDENCE", "medical_context"),
    ("How to treat a headache?", "EVIDENCE", "medical_context"),
    ("Diabetes medication", "EVIDENCE", "medical_context"),
    ("Heart attack symptoms", "EVIDENCE", "medical_context"),

    # --- LOCAL: personal finance reasoning (not live data) ---
    ("What would you consider a comfortable bank balance?", "LOCAL", "personal_finance_reasoning"),
    ("How should I budget for retirement?", "LOCAL", "personal_finance_reasoning"),
    ("Should I invest in stocks or bonds?", "LOCAL", "personal_finance_reasoning"),

    # --- AUGMENTED: live financial data ---
    ("What is the current stock price of Apple?", "AUGMENTED", "financial_data"),
    ("Bitcoin price today", "AUGMENTED", "financial_data"),

    # --- NEWS: conflict / live news ---
    ("Breaking news about the war", "NEWS", "conflict_live"),
    ("Current situation in Gaza", "NEWS", "conflict_live"),

    # --- LOCAL: creative writing guard ---
    ("Write a horror story about a hospital", "LOCAL", "creative_writing"),
    ("Tell me a joke", "LOCAL", "default_light"),

    # --- Boundary: pet without symptoms (must stay LOCAL) ---
    ("My dog likes to play fetch", "LOCAL", "personal_family_context"),
    ("My cat sleeps all day", "LOCAL", "personal_family_context"),
    ("Do I have a pet?", "LOCAL", "personal_family_context"),
]


def run_burnin():
    """Run the policy hybrid burn-in test."""
    log_dir = Path(os.environ["LUCY_ROUTER_LOG_DIR"])
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "router_decisions_policy_burnin.jsonl"

    print("=" * 80)
    print("POLICY HYBRID BURN-IN")
    print("=" * 80)
    print(f"Queries: {len(BURNIN_QUERIES)}")
    print(f"Log: {log_path}")
    print("")

    results = []
    start_all = time.time()

    for query, expected_route, expected_reason in BURNIN_QUERIES:
        t0 = time.time()
        try:
            classification = classify_intent(query, surface="hmi")
            policy = normalize_augmentation_policy("fallback_only")
            decision = select_route(classification, policy=policy, query=query)
            elapsed_ms = (time.time() - t0) * 1000

            # Check expectations
            route_ok = decision.route == expected_route
            reason_ok = decision.evidence_reason == expected_reason
            passed = route_ok and reason_ok

            result = {
                "query": query,
                "expected_route": expected_route,
                "actual_route": decision.route,
                "expected_reason": expected_reason,
                "actual_reason": decision.evidence_reason,
                "route_ok": route_ok,
                "reason_ok": reason_ok,
                "passed": passed,
                "elapsed_ms": round(elapsed_ms, 2),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            results.append(result)

            # Also append to jsonl log
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(result, ensure_ascii=False) + "\n")

        except Exception as e:
            results.append({
                "query": query,
                "expected_route": expected_route,
                "expected_reason": expected_reason,
                "passed": False,
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            print(f"  ERROR: {query!r} -> {e}")

    total_elapsed = (time.time() - start_all) * 1000

    # --- Summary table ---
    print(f"{'Query':<50} {'Exp':<10} {'Act':<10} {'Reason':<30} {'Time'}")
    print("-" * 110)
    failures = []
    for r in results:
        status = "✓" if r.get("passed") else "✗"
        line = (
            f"{r['query']:<50} "
            f"{r['expected_route']:<10} "
            f"{r.get('actual_route', 'ERR'):<10} "
            f"{r.get('actual_reason', r.get('error', 'N/A')):<30} "
            f"{r.get('elapsed_ms', 0):.0f}ms"
        )
        print(f"{status} {line}")
        if not r.get("passed"):
            failures.append(r)

    print("-" * 110)
    passed = sum(1 for r in results if r.get("passed"))
    total = len(results)
    rate = (passed / total * 100) if total else 0
    print(f"\nPassed: {passed}/{total} ({rate:.1f}%)")
    print(f"Total time: {total_elapsed:.0f}ms  |  Avg: {total_elapsed/total:.1f}ms")

    if failures:
        print("\n" + "=" * 80)
        print("FAILURES")
        print("=" * 80)
        for f in failures:
            print(f"  Query:    {f['query']}")
            print(f"  Expected: {f['expected_route']} / {f['expected_reason']}")
            print(f"  Actual:   {f.get('actual_route', 'ERR')} / {f.get('actual_reason', 'N/A')}")
            if "error" in f:
                print(f"  Error:    {f['error']}")
            print()
        sys.exit(1)
    else:
        print("\n🏆 ALL GREEN — Policy hybrid layer is production-ready.")
        print(f"   Log written to: {log_path}")


if __name__ == "__main__":
    run_burnin()
