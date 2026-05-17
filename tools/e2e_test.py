#!/usr/bin/env python3
"""
Local Lucy V8 — End-to-End Integration Test
Actually invokes LLM and external providers. Be patient.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ["LUCY_EXEC_PY"] = "1"
os.environ["LUCY_ROUTER_PY"] = "1"
os.environ["LUCY_SESSION_MEMORY"] = "1"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from router_py.main import run

results = []
start_time = time.time()

def log(stage: str, name: str, ok: bool, detail: str = ""):
    status = "PASS" if ok else "FAIL"
    elapsed = time.time() - start_time
    results.append((elapsed, stage, status, name, detail))
    print(f"  [{status:4s}] {stage:18s} | {name:38s} {detail}")

print("=" * 70)
print("END-TO-END INTEGRATION TEST")
print("This test invokes the actual LLM and external APIs.")
print("Be patient — qwen3 14B on RTX 3060 takes 15-45s per LLM call.")
print("=" * 70)

# --- Check if Ollama is available ---
print("\nChecking Ollama availability...")
try:
    import urllib.request
    req = urllib.request.Request("http://127.0.0.1:11434/api/tags", method="GET")
    req.add_header("Accept", "application/json")
    with urllib.request.urlopen(req, timeout=5) as resp:
        ollama_ok = resp.status == 200
        print(f"  Ollama: {'reachable' if ollama_ok else 'unreachable'}")
except Exception as e:
    ollama_ok = False
    print(f"  Ollama: unreachable ({e})")

# --- Test 1: TIME route (fast, no LLM) ---
print("\n1. TIME route (fast)")
t0 = time.time()
try:
    outcome = run("What time is it?", surface="cli", timeout=30)
    dt = time.time() - t0
    log("TIME", "Current time query", outcome.route == "TIME" and outcome.status == "completed",
        f"{outcome.route} | {outcome.response_text[:40]}... | {dt:.1f}s")
except Exception as e:
    log("TIME", "Current time query", False, str(e)[:50])

# --- Test 2: WEATHER route (fast, no LLM) ---
print("\n2. WEATHER route (fast)")
t0 = time.time()
try:
    outcome = run("What's the weather in London?", surface="cli", timeout=30)
    dt = time.time() - t0
    log("WEATHER", "London weather", outcome.route == "WEATHER" and outcome.status == "completed",
        f"{outcome.route} | {outcome.response_text[:40]}... | {dt:.1f}s")
except Exception as e:
    log("WEATHER", "London weather", False, str(e)[:50])

# --- Test 3: LOCAL route (LLM via Ollama) ---
if ollama_ok:
    print("\n3. LOCAL route (LLM — this will take 15-45s)")
    t0 = time.time()
    try:
        outcome = run("What is 2+2?", surface="cli", timeout=120)
        dt = time.time() - t0
        has_response = len(outcome.response_text or "") > 5
        log("LOCAL", "Simple math query", outcome.route == "LOCAL" and has_response,
            f"{outcome.route} | len={len(outcome.response_text)} | {dt:.1f}s")
    except Exception as e:
        log("LOCAL", "Simple math query", False, str(e)[:50])
else:
    log("LOCAL", "Simple math query", False, "Ollama not available")

# --- Test 4: AUGMENTED + Wikipedia (evidence fetch + LLM) ---
if ollama_ok:
    print("\n4. AUGMENTED + Wikipedia (evidence + LLM — ~30-60s)")
    os.environ["LUCY_AUGMENTED_PROVIDER"] = "wikipedia"
    t0 = time.time()
    try:
        outcome = run("augmented: What is photosynthesis?", policy="direct_allowed", surface="cli", timeout=180)
        dt = time.time() - t0
        has_evidence = "wikipedia" in (outcome.response_text or "").lower() or len(outcome.response_text or "") > 50
        log("AUGMENTED", "Wikipedia + LLM", outcome.route == "AUGMENTED" and has_evidence,
            f"{outcome.route}/{outcome.provider} | len={len(outcome.response_text)} | {dt:.1f}s")
    except Exception as e:
        log("AUGMENTED", "Wikipedia + LLM", False, str(e)[:50])
else:
    log("AUGMENTED", "Wikipedia + LLM", False, "Ollama not available")

# --- Test 5: Feedback detection (fast) ---
print("\n5. Feedback detection (fast)")
t0 = time.time()
try:
    outcome = run("That was wrong", surface="cli", timeout=30)
    dt = time.time() - t0
    log("Feedback", "Negative feedback", outcome.outcome_code == "feedback_acknowledged",
        f"{outcome.outcome_code} | {dt:.1f}s")
except Exception as e:
    log("Feedback", "Negative feedback", False, str(e)[:50])

# --- Test 6: Prefix override (fast routing check) ---
print("\n6. Prefix override (fast)")
t0 = time.time()
try:
    outcome = run("local: What is the theory of relativity?", surface="cli", timeout=120)
    dt = time.time() - t0
    log("Prefix", "local: prefix", outcome.route == "LOCAL",
        f"{outcome.route} | {dt:.1f}s")
except Exception as e:
    log("Prefix", "local: prefix", False, str(e)[:50])

# --- Summary ---
print("\n" + "=" * 70)
print("END-TO-END TEST SUMMARY")
print("=" * 70)

passed = sum(1 for r in results if r[2] == "PASS")
failed = sum(1 for r in results if r[2] == "FAIL")
total_time = time.time() - start_time

print(f"\nTests run:    {len(results)}")
print(f"Passed:       {passed}")
print(f"Failed:       {failed}")
print(f"Total time:   {total_time:.1f}s")

if failed > 0:
    print("\nFAILED:")
    for elapsed, stage, status, name, detail in results:
        if status == "FAIL":
            print(f"  [{stage}] {name}: {detail}")

print("\n" + "=" * 70)
if failed == 0:
    print("ALL END-TO-END TESTS PASSED ✅")
else:
    print(f"END-TO-END: {passed}/{len(results)} PASSED")
print("=" * 70)
