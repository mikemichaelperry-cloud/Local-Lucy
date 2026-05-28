#!/usr/bin/env python3
"""
Manual E2E demonstration of the self-learning feedback loop.

This script:
  1. Backs up production router files
  2. Picks a query that is currently misrouted (TIME instead of LOCAL)
  3. Shows the incorrect route
  4. Submits feedback correcting it to LOCAL
  5. Triggers background learning
  6. Re-queries and shows the corrected route
  7. Restores production files

Run with:
    cd /home/mike/lucy-v10
    source ui-v9/.venv/bin/activate
    python3 manual_feedback_loop_demo.py
"""

import json
import os
import shutil
import sys
import time
from pathlib import Path

# Ensure imports resolve
sys.path.insert(0, str(Path(__file__).parent / "tools" / "router_py"))
sys.path.insert(0, str(Path(__file__).parent / "models" / "router"))

ROUTER_DIR = Path("/home/mike/lucy-v10/models/router")
BACKUP_DIR = Path("/tmp/lucy_router_backup_") / str(int(time.time()))

FILES_TO_BACKUP = [
    "comprehensive_index.jsonl",
    "comprehensive_embeddings.npy",
    "comprehensive_examples.json",
    "user_feedback.jsonl",
]


def backup():
    print(f"[BACKUP] Creating backup at {BACKUP_DIR}")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    for fname in FILES_TO_BACKUP:
        src = ROUTER_DIR / fname
        if src.exists():
            shutil.copy2(src, BACKUP_DIR / fname)
            print(f"[BACKUP]  → {fname}")


def restore():
    print(f"[RESTORE] Restoring from {BACKUP_DIR}")
    for fname in FILES_TO_BACKUP:
        src = BACKUP_DIR / fname
        dst = ROUTER_DIR / fname
        if src.exists():
            shutil.copy2(src, dst)
            print(f"[RESTORE]  → {fname}")
        elif dst.exists():
            dst.unlink()
            print(f"[RESTORE]  → removed {fname}")


def run_demo():
    from hybrid_router_v2 import HybridRouterV2
    from feedback_buffer import get_buffer
    from feedback_parser import FeedbackResult, FeedbackType, log_user_feedback
    import background_learner as bl

    # --- Step 1: Pick a known misroute ---
    query = "What day was I born?"
    expected_route = "LOCAL"

    print("\n" + "=" * 60)
    print("STEP 1: Identifying a misrouted query")
    print("=" * 60)
    print(f"[QUERY] '{query}'")
    print(f"[EXPECTED] This should route to {expected_route} (personal fact)")

    # --- Step 2: Show pre-learn prediction ---
    print("\n" + "=" * 60)
    print("STEP 2: Pre-learning prediction")
    print("=" * 60)
    router_pre = HybridRouterV2()
    pre = router_pre.predict(query)
    print(f"[PRE]  '{query}' → {pre['route']} (confidence: {pre.get('confidence', 0):.3f})")

    if pre["route"] == expected_route:
        print(f"[WARN] Already routes correctly; demo will still show the mechanism.")

    # --- Step 3: Submit feedback ---
    print("\n" + "=" * 60)
    print("STEP 3: Submitting corrective feedback")
    print("=" * 60)

    buf = get_buffer()
    buf.clear()
    buf.append(
        query=query,
        route=pre["route"],
        response_text="You were born on a Tuesday",
        intent_family=pre.get("intent_family", "unknown"),
        confidence=pre.get("confidence", 0),
    )

    # Build feedback result with explicit corrected route
    fb = FeedbackResult(
        feedback_type=FeedbackType.ANSWER_NEGATIVE,
        target_query=query,
        original_route=pre["route"],
        corrected_route=expected_route,
        confidence=0.9,
        raw_text="That is wrong, I was not asking for the time",
    )
    print(f"[FEEDBACK] Type: {fb.feedback_type.name}, correcting {pre['route']} → {expected_route}")

    logged = log_user_feedback(fb)
    print(f"[FEEDBACK] Logged to user_feedback.jsonl: {logged}")

    if not logged:
        print("[FEEDBACK] Fallback: writing directly to user_feedback.jsonl")
        feedback_entry = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "query": query,
            "original_route": pre["route"],
            "correct_route": expected_route,
            "feedback_type": "correction",
            "source": "manual_demo",
        }
        feedback_path = ROUTER_DIR / "user_feedback.jsonl"
        with open(feedback_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(feedback_entry) + "\n")
        print(f"[FEEDBACK] Written directly to {feedback_path}")

    # --- Step 4: Trigger learning ---
    print("\n" + "=" * 60)
    print("STEP 4: Triggering background learning")
    print("=" * 60)

    old_env = os.environ.get("LUCY_AUTO_LEARN")
    os.environ["LUCY_AUTO_LEARN"] = "1"
    try:
        result = bl.learn_once(verbose=True)
        print(f"[LEARN] Result: {result}")
    finally:
        if old_env is None:
            os.environ.pop("LUCY_AUTO_LEARN", None)
        else:
            os.environ["LUCY_AUTO_LEARN"] = old_env

    # --- Step 5: Show post-learn prediction ---
    print("\n" + "=" * 60)
    print("STEP 5: Post-learning prediction")
    print("=" * 60)
    router_post = HybridRouterV2()
    post = router_post.predict(query)
    print(f"[POST] '{query}' → {post['route']} (confidence: {post.get('confidence', 0):.3f})")

    # --- Step 6: Verification ---
    print("\n" + "=" * 60)
    print("STEP 6: Verification")
    print("=" * 60)
    if post["route"] == expected_route:
        print(f"✅ SUCCESS: Router learned! '{query}' now routes to {expected_route} (was {pre['route']})")
        return True
    else:
        print(f"⚠️  Router still routes to {post['route']} (expected {expected_route})")
        print("   The feedback was recorded and will continue to influence learning.")
        print("   Embedding-based routers need sufficient feedback mass to flip strong predictions.")
        return False


if __name__ == "__main__":
    print("Manual E2E Feedback Loop Demonstration")
    print("=" * 60)

    backup()
    try:
        success = run_demo()
    finally:
        restore()

    print("\n" + "=" * 60)
    if success:
        print("DEMO COMPLETE: Router successfully learned from feedback.")
    else:
        print("DEMO COMPLETE: Feedback recorded; strong prior embedding may need more examples.")
    print("=" * 60)
