#!/usr/bin/env python3
"""Background learner — continuously improves embedding index from usage.

Watches shadow divergence logs and adds new examples to the embedding index.
Can also ingest explicit user feedback (thumbs up/down on routing decisions).

Usage:
    # Run once to process pending logs
    python background_learner.py --process

    # Run as daemon (checks every 60 seconds)
    python background_learner.py --daemon --interval 60

    # Add explicit feedback
    python background_learner.py --feedback \"What is 2+2?\" --route LOCAL --correct
"""

import argparse
import fcntl
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

# Import hybrid router components
sys.path.insert(0, str(Path(__file__).parent))
from embedding_router import EmbeddingRouter


# Paths
ROUTER_DIR = Path(__file__).parent
INDEX_PATH = ROUTER_DIR / "comprehensive_index.jsonl"
EMBEDDINGS_PATH = ROUTER_DIR / "comprehensive_embeddings.npy"
EXAMPLES_PATH = ROUTER_DIR / "comprehensive_examples.json"
FEEDBACK_PATH = ROUTER_DIR / "user_feedback.jsonl"
LEARNED_PATH = ROUTER_DIR / "learned_examples.jsonl"

# Lock file for atomic updates
LOCK_PATH = ROUTER_DIR / ".learner_lock"


def acquire_lock():
    """Acquire file lock for atomic index updates."""
    lock_file = open(LOCK_PATH, "w")
    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
    return lock_file


def release_lock(lock_file):
    """Release file lock."""
    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    lock_file.close()


def load_index() -> list[dict]:
    """Load current embedding index."""
    examples = []
    if INDEX_PATH.exists():
        with open(INDEX_PATH) as f:
            for line in f:
                line = line.strip()
                if line:
                    examples.append(json.loads(line))
    return examples


def save_index(examples: list[dict]):
    """Save embedding index atomically."""
    import tempfile
    tmp = tempfile.NamedTemporaryFile(
        mode="w", dir=ROUTER_DIR, delete=False,
        prefix=".comprehensive_index.", suffix=".tmp"
    )
    for ex in examples:
        tmp.write(json.dumps(ex) + "\n")
    tmp.close()
    os.replace(tmp.name, INDEX_PATH)


def rebuild_embeddings(examples: list[dict]):
    """Rebuild embedding matrix from examples."""
    print(f"  Rebuilding embeddings for {len(examples)} examples...")
    router = EmbeddingRouter()
    router.fit(examples)
    np.save(EMBEDDINGS_PATH, router.embeddings)
    with open(EXAMPLES_PATH, "w") as f:
        json.dump(router.examples, f, indent=2)
    print(f"  Saved: {EMBEDDINGS_PATH} ({router.embeddings.shape})")


def deduplicate(examples: list[dict]) -> list[dict]:
    """Remove duplicate queries, keeping the most recent label."""
    seen = {}
    for ex in examples:
        key = ex["query"].lower().strip()
        seen[key] = ex  # Overwrite with latest
    return list(seen.values())


def process_router_logs(log_path: Path, min_confidence: float = 0.7) -> list[dict]:
    """Process single-path router decision logs and extract learning examples.

    Reads router_decisions.jsonl and adds each unique query with its final
    route as a labeled example. Only high-confidence decisions are used to
    avoid polluting the index with uncertain predictions.
    """
    if not log_path.exists():
        return []

    new_examples = []
    with open(log_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            query = entry.get("query", "").strip()
            if not query or len(query) < 3:
                continue

            # Skip test/junk queries
            if any(j in query.lower() for j in ["test query", "2+2 2+2"]):
                continue

            route = entry.get("route", "")
            confidence = entry.get("confidence", 0)
            intent = entry.get("intent", "local_answer")
            evidence_reason = entry.get("evidence_reason", "")

            # Only learn from confident decisions
            if confidence < min_confidence:
                continue

            evidence = "required" if evidence_reason else "not_required"

            new_examples.append({
                "query": query,
                "labels": {
                    "intent_family": intent,
                    "evidence_mode": evidence,
                    "route": route,
                    "policy_override": "none",
                },
                "metadata": {
                    "source": "router_log",
                    "confidence": confidence,
                    "guards_fired": entry.get("guards_fired", []),
                    "embedding_route": entry.get("embedding_route", ""),
                },
            })

    return new_examples


def process_user_feedback() -> list[dict]:
    """Process explicit user feedback (thumbs up/down)."""
    if not FEEDBACK_PATH.exists():
        return []

    new_examples = []
    with open(FEEDBACK_PATH) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            query = entry.get("query", "").strip()
            correct_route = entry.get("correct_route", "")
            if not query or not correct_route:
                continue

            sys.path.insert(0, str(Path(__file__).parent.parent.parent / "tools" / "router_py"))
            from policy import requires_evidence_mode
            requires_evidence, _ = requires_evidence_mode(query)
            evidence = "required" if requires_evidence else "not_required"

            new_examples.append({
                "query": query,
                "labels": {
                    "intent_family": _route_to_intent(correct_route),
                    "evidence_mode": evidence,
                    "route": correct_route,
                    "policy_override": "none",
                },
                "metadata": {
                    "source": "user_feedback",
                    "feedback_type": entry.get("feedback_type", "correction"),
                    "timestamp": entry.get("timestamp", ""),
                },
            })

    return new_examples


def _route_to_intent(route: str) -> str:
    """Map route back to intent_family."""
    mapping = {
        "LOCAL": "local_answer",
        "LOCAL_WITH_FALLBACK": "background_overview",
        "AUGMENTED": "current_evidence",
        "NEWS": "news_request",
        "TIME": "time_query",
        "CLARIFY": "clarification",
    }
    return mapping.get(route, "local_answer")


def learn_once(log_path: Path | None = None, verbose: bool = True) -> dict:
    """Single learning iteration: process logs, update index, rebuild embeddings."""
    if verbose:
        print("=" * 60)
        print("Background Learner")
        print("=" * 60)

    lock = acquire_lock()
    try:
        # Load current index
        examples = load_index()
        original_count = len(examples)
        if verbose:
            print(f"Current index: {original_count} examples")

        # Process router decision logs
        new_from_logs = []
        if log_path and log_path.exists():
            new_from_logs = process_router_logs(log_path)
            if verbose:
                print(f"New from router logs: {len(new_from_logs)}")

        # Process user feedback
        new_from_feedback = process_user_feedback()
        if verbose:
            print(f"New from user feedback: {len(new_from_feedback)}")

        # Process auto-feedback from answer quality analysis
        new_from_auto = process_auto_feedback()
        if verbose:
            print(f"New from auto-feedback: {len(new_from_auto)}")

        # Combine and deduplicate
        all_examples = examples + new_from_logs + new_from_feedback + new_from_auto
        all_examples = deduplicate(all_examples)

        added = len(all_examples) - original_count
        if verbose:
            print(f"Total after dedup: {len(all_examples)} (+{added})")

        if added > 0:
            # Save updated index
            save_index(all_examples)

            # Rebuild embeddings
            rebuild_embeddings(all_examples)

            # Mark feedback as processed
            if FEEDBACK_PATH.exists():
                processed_path = FEEDBACK_PATH.with_suffix(".processed")
                os.replace(FEEDBACK_PATH, processed_path)

            # Mark auto-feedback as processed
            from auto_feedback import clear_auto_feedback
            clear_auto_feedback()

            if verbose:
                print(f"\n✅ Index updated: +{added} examples")
        else:
            if verbose:
                print("\n⏭ No new examples to add")

        return {
            "original_count": original_count,
            "new_from_logs": len(new_from_logs),
            "new_from_feedback": len(new_from_feedback),
            "new_from_auto": len(new_from_auto),
            "added": added,
            "total": len(all_examples),
        }

    finally:
        release_lock(lock)


def add_feedback(query: str, correct_route: str, feedback_type: str = "correction"):
    """Add explicit user feedback for a query.

    Args:
        query: The user query
        correct_route: The correct route (LOCAL, AUGMENTED, NEWS, TIME, CLARIFY)
        feedback_type: 'correction' (legacy was wrong) or 'confirmation' (legacy was right)
    """
    entry = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "query": query,
        "correct_route": correct_route,
        "feedback_type": feedback_type,
    }
    with open(FEEDBACK_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    print(f"Feedback recorded: '{query[:50]}...' -> {correct_route}")


def run_daemon(log_path: Path | None, interval: int = 60):
    """Run learner as a daemon process."""
    print(f"Background learner daemon started")
    print(f"  Shadow log: {log_path}")
    print(f"  Check interval: {interval}s")
    print(f"  Index: {INDEX_PATH}")
    print(f"  Press Ctrl+C to stop\n")

    last_size = log_path.stat().st_size if log_path and log_path.exists() else 0

    try:
        while True:
            current_size = log_path.stat().st_size if log_path and log_path.exists() else 0
            if current_size > last_size:
                result = learn_once(log_path, verbose=True)
                last_size = current_size
            else:
                print(f"[{time.strftime('%H:%M:%S')}] No new data, sleeping...")

            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nDaemon stopped.")


def process_auto_feedback() -> list[dict]:
    """Process auto-feedback from answer quality analysis."""
    sys.path.insert(0, str(ROUTER_DIR))
    try:
        from auto_feedback import load_auto_feedback, clear_auto_feedback
    except ImportError:
        return []

    entries = load_auto_feedback(min_confidence=0.6)
    new_examples = []
    for entry in entries:
        query = entry.get("query", "").strip()
        correct_route = entry.get("correct_route", "")
        if not query or not correct_route:
            continue

        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "tools" / "router_py"))
        from policy import requires_evidence_mode
        requires_evidence, _ = requires_evidence_mode(query)
        evidence = "required" if requires_evidence else "not_required"

        new_examples.append({
            "query": query,
            "labels": {
                "intent_family": _route_to_intent(correct_route),
                "evidence_mode": evidence,
                "route": correct_route,
                "policy_override": "none",
            },
            "metadata": {
                "source": "auto_feedback",
                "reason": entry.get("reason", ""),
                "confidence": entry.get("confidence", 0),
                "timestamp": entry.get("timestamp", ""),
            },
        })

    return new_examples


def main():
    parser = argparse.ArgumentParser(description="Background learner for embedding router")
    parser.add_argument("--process", action="store_true", help="Process logs once and exit")
    parser.add_argument("--daemon", action="store_true", help="Run as daemon")
    parser.add_argument("--interval", type=int, default=60, help="Daemon check interval (seconds)")
    parser.add_argument("--log-path", type=Path, help="Shadow divergence log path")
    parser.add_argument("--feedback", type=str, help="Add user feedback: query string")
    parser.add_argument("--route", type=str, help="Correct route for feedback")
    parser.add_argument("--correct", action="store_true", help="Mark feedback as confirmation (legacy was right)")
    args = parser.parse_args()

    # Determine log path
    log_path = args.log_path
    if not log_path:
        router_dir = os.environ.get("LUCY_ROUTER_LOG_DIR")
        if router_dir:
            log_path = Path(router_dir) / "router_decisions.jsonl"

    if args.feedback and args.route:
        feedback_type = "confirmation" if args.correct else "correction"
        add_feedback(args.feedback, args.route, feedback_type)
        # Also trigger a learn cycle
        learn_once(log_path)
        return

    if args.daemon:
        run_daemon(log_path, args.interval)
    else:
        learn_once(log_path, verbose=True)


if __name__ == "__main__":
    main()
