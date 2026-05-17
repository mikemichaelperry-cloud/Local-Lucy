#!/usr/bin/env python3
"""
Local Lucy V8 — Thrash Test
Pushes the unified Python-native path to its limits.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import os
import random
import string
import sys
import tempfile
import time
from pathlib import Path

os.environ["LUCY_EXEC_PY"] = "1"
os.environ["LUCY_ROUTER_PY"] = "1"
os.environ["LUCY_SESSION_MEMORY"] = "1"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from router_py.main import run
from router_py.classify import classify_intent, select_route, _memory_routing_gate
from router_py.execution_engine import ExecutionEngine

results = []
start_time = time.time()

def log(stage: str, name: str, ok: bool, detail: str = ""):
    status = "PASS" if ok else "FAIL"
    elapsed = time.time() - start_time
    results.append((elapsed, stage, status, name, detail))
    print(f"  [{status:4s}] {stage:20s} | {name:40s} {detail}")

# ============================================================================
# STAGE 1: BASIC FUNCTIONALITY
# ============================================================================
print("=" * 70)
print("STAGE 1: Basic Functionality")
print("=" * 70)

basic_queries = [
    ("What time is it?", "TIME"),
    ("What's the weather in London?", "WEATHER"),
    ("Tell me about photosynthesis", "AUGMENTED"),
    ("What is 2+2?", "LOCAL"),
    ("Write me a haiku about cats", "LOCAL"),
    ("augmented: Explain quantum computing", "AUGMENTED"),
    ("local: What is your name?", "LOCAL"),
    ("news: What's happening today?", "NEWS"),
]

for query, expected_route in basic_queries:
    try:
        outcome = run(query, surface="cli", timeout=30)
        ok = outcome.status == "completed"
        log("Basic", f"{query[:40]}", ok, f"route={outcome.route}")
    except Exception as e:
        log("Basic", f"{query[:40]}", False, str(e)[:50])

# ============================================================================
# STAGE 2: PROVIDER PREFERENCE HAMMERING
# ============================================================================
print("\n" + "=" * 70)
print("STAGE 2: Provider Preference Hammering")
print("=" * 70)

providers = ["wikipedia", "openai", "kimi"]
for provider in providers:
    os.environ["LUCY_AUGMENTED_PROVIDER"] = provider
    for i in range(5):
        try:
            outcome = run("augmented: What is general relativity?", policy="direct_allowed", surface="cli", timeout=30)
            ok = outcome.provider == provider
            log("Provider", f"{provider} #{i+1}", ok, f"got={outcome.provider}")
        except Exception as e:
            log("Provider", f"{provider} #{i+1}", False, str(e)[:50])

del os.environ["LUCY_AUGMENTED_PROVIDER"]

# ============================================================================
# STAGE 3: GARBAGE / MALFORMED INPUTS
# ============================================================================
print("\n" + "=" * 70)
print("STAGE 3: Garbage & Malformed Inputs")
print("=" * 70)

garbage_inputs = [
    "",  # empty
    "   ",  # whitespace
    "!@#$%^&*()",  # special chars
    "a",  # single char
    "x" * 5000,  # 5KB of x
    "\x00\x01\x02",  # binary
    "\n\r\t",  # control chars
    "日本語テスト",  # Japanese
    "العربية",  # Arabic
    "local:",  # prefix with no query
    "augmented:   ",  # prefix + whitespace
    "DROP TABLE users;",  # SQL injection attempt
    "<script>alert(1)</script>",  # XSS attempt
]

for g in garbage_inputs:
    try:
        outcome = run(g, surface="cli", timeout=30)
        ok = outcome.status in ("completed", "failed")
        log("Garbage", repr(g)[:40], ok, f"status={outcome.status}")
    except Exception as e:
        log("Garbage", repr(g)[:40], False, f"CRASH: {str(e)[:40]}")

# ============================================================================
# STAGE 4: RAPID-FIRE SEQUENTIAL
# ============================================================================
print("\n" + "=" * 70)
print("STAGE 4: Rapid-Fire Sequential (50 queries)")
print("=" * 70)

rapid_queries = [
    "What time is it?", "Weather in Paris", "Explain gravity",
    "Who won the world series?", "What is pi?", "Tell me a joke",
    "news: headlines", "augmented: quantum mechanics",
] * 6 + ["What time is it?", "Weather in Tokyo"]

success = 0
fail = 0
for i, q in enumerate(rapid_queries):
    try:
        outcome = run(q, surface="cli", timeout=30)
        if outcome.status == "completed":
            success += 1
        else:
            fail += 1
    except Exception as e:
        fail += 1

log("Rapid", f"50 queries", fail == 0, f"success={success} fail={fail}")

# ============================================================================
# STAGE 5: CONCURRENT SUBMISSIONS
# ============================================================================
print("\n" + "=" * 70)
print("STAGE 5: Concurrent Submissions (8 threads, 3 queries each)")
print("=" * 70)

concurrent_queries = [
    "What time is it?", "Weather in Berlin", "Explain entropy",
    "Who wrote Hamlet?", "What is the speed of light?", "Tell me a riddle",
    "news: breaking news", "augmented: string theory",
] * 3

success_c = 0
fail_c = 0
lock = False

def run_query(q):
    global success_c, fail_c
    try:
        outcome = run(q, surface="cli", timeout=30)
        if outcome.status == "completed":
            success_c += 1
        else:
            fail_c += 1
    except Exception as e:
        fail_c += 1

with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
    futures = [executor.submit(run_query, q) for q in concurrent_queries]
    concurrent.futures.wait(futures)

log("Concurrent", f"24 queries (8 workers)", fail_c < 5, f"success={success_c} fail={fail_c}")

# ============================================================================
# STAGE 6: MEMORY GATE STRESS
# ============================================================================
print("\n" + "=" * 70)
print("STAGE 6: Memory Gate Stress")
print("=" * 70)

# Store some memory
from memory.memory_service import store_turn, clear_session
try:
    clear_session()
    store_turn("user", "My dog is named Max.")
    store_turn("assistant", "Got it, your dog is Max.")

    gate_tests = [
        ("What did I say about him?", "WEATHER", "LOCAL"),
        ("What is the weather in London?", "WEATHER", None),
        ("Tell me about him", "WEATHER", "LOCAL"),
        ("What did I say?", "NEWS", "LOCAL"),
        ("What are the headlines?", "NEWS", None),
    ]

    for query, route, expected in gate_tests:
        result = _memory_routing_gate(query, route)
        ok = result == expected
        log("MemoryGate", f"{query[:30]}", ok, f"expected={expected} got={result}")
except Exception as e:
    log("MemoryGate", "setup", False, str(e)[:50])

# ============================================================================
# STAGE 7: ROUTING EDGE CASES
# ============================================================================
print("\n" + "=" * 70)
print("STAGE 7: Routing Edge Cases")
print("=" * 70)

edge_cases = [
    ("How do I fix a leaky faucet?", "LOCAL"),  # DIY
    ("What is the capital of France?", None),  # Ambiguous
    ("Tell me about Mars", "LOCAL"),  # Planet exclusion
    ("What was the weather like in 2010?", "LOCAL"),  # Historical exclusion
    ("Kid friendly recipes", "LOCAL"),  # Cooking
    ("stocks today", None),  # Financial (may be LOCAL or AUGMENTED)
    ("breaking news headlines", "NEWS"),  # News
]

for query, expected in edge_cases:
    try:
        cl = classify_intent(query, surface="cli")
        decision = select_route(cl, policy="fallback_only", query=query)
        ok = expected is None or decision.route == expected
        log("Routing", f"{query[:35]}", ok, f"route={decision.route} exp={expected}")
    except Exception as e:
        log("Routing", f"{query[:35]}", False, str(e)[:50])

# ============================================================================
# STAGE 8: FEEDBACK DETECTION
# ============================================================================
print("\n" + "=" * 70)
print("STAGE 8: Feedback Detection")
print("=" * 70)

feedback_queries = [
    "That was wrong",
    "That was right",
    "That should route to NEWS",
    "I retract that",
    "Noted",
]

for q in feedback_queries:
    try:
        outcome = run(q, surface="cli", timeout=30)
        ok = outcome.outcome_code == "feedback_acknowledged"
        log("Feedback", q, ok, f"code={outcome.outcome_code}")
    except Exception as e:
        log("Feedback", q, False, str(e)[:50])

# ============================================================================
# STAGE 9: SHELL SHIM STRESS
# ============================================================================
print("\n" + "=" * 70)
print("STAGE 9: Shell Shim Stress")
print("=" * 70)

import subprocess

shim_ok = 0
shim_fail = 0
for i in range(10):
    try:
        r = subprocess.run(
            ["bash", "/home/mike/lucy-v9/tools/router/execute_plan.sh", "What time is it?"],
            capture_output=True, text=True, timeout=30
        )
        if r.returncode == 0 and "time" in r.stdout.lower():
            shim_ok += 1
        else:
            shim_fail += 1
    except Exception as e:
        shim_fail += 1

log("Shim", "10 sequential calls", shim_fail == 0, f"ok={shim_ok} fail={shim_fail}")

# ============================================================================
# STAGE 10: STATE FILE STRESS
# ============================================================================
print("\n" + "=" * 70)
print("STAGE 10: State File Stress")
print("=" * 70)

state_dir = Path("/home/mike/lucy-v9/state/namespaces/default")
outcome_file = state_dir / "last_outcome.env"

if outcome_file.exists():
    content = outcome_file.read_text()
    has_fields = all(f in content for f in ["OUTCOME_CODE=", "FINAL_MODE=", "PROVIDER="])
    log("StateFile", "last_outcome.env", has_fields, f"size={len(content)} bytes")
else:
    log("StateFile", "last_outcome.env", False, "missing")

# ============================================================================
# SUMMARY
# ============================================================================
print("\n" + "=" * 70)
print("THRASH TEST SUMMARY")
print("=" * 70)

passed = sum(1 for r in results if r[2] == "PASS")
failed = sum(1 for r in results if r[2] == "FAIL")
total = len(results)
total_time = time.time() - start_time

print(f"\nTotal tests: {total}")
print(f"Passed:      {passed}")
print(f"Failed:      {failed}")
print(f"Total time:  {total_time:.1f}s")
print(f"Avg/test:    {total_time/total:.2f}s")

if failed > 0:
    print("\nFAILED DETAILS:")
    for elapsed, stage, status, name, detail in results:
        if status == "FAIL":
            print(f"  [{stage}] {name}: {detail}")

print("\n" + "=" * 70)
if failed == 0:
    print("ALL THRASH TESTS PASSED — LOCAL LUCY IS ROCK SOLID 💪")
elif failed <= 3:
    print(f"THRASH TEST MOSTLY PASSED — {failed} minor issues")
else:
    print(f"THRASH TEST FOUND {failed} ISSUES — NEEDS ATTENTION")
print("=" * 70)
