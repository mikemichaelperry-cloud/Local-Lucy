#!/usr/bin/env python3
"""Background learner — continuously improves embedding index from usage.

Processes three sources of learning signal:
  1. Router decision logs (high-confidence decisions)
  2. Explicit user feedback (--feedback CLI)
  3. Auto-feedback from answer quality analysis (execution engine)

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
from hybrid_router_v2 import HybridRouterV2


# Paths
ROUTER_DIR = Path(__file__).parent
INDEX_PATH = ROUTER_DIR / "comprehensive_index.jsonl"
EMBEDDINGS_PATH = ROUTER_DIR / "comprehensive_embeddings.npy"
EXAMPLES_PATH = ROUTER_DIR / "comprehensive_examples.json"
EXAMPLES_METADATA_PATH = ROUTER_DIR / "examples_metadata.json"
FEEDBACK_PATH = ROUTER_DIR / "user_feedback.jsonl"
LEARNED_PATH = ROUTER_DIR / "learned_examples.jsonl"
LOG_PROGRESS_PATH = ROUTER_DIR / ".router_log_progress"

# Lock file for atomic updates
LOCK_PATH = ROUTER_DIR / ".learner_lock"

# Kill-switch: if this file exists, auto-learning is paused
DISABLE_FLAG = ROUTER_DIR / ".learner_disable"

# Old keyword-guard markers from the pre-V2 era.  Router log entries that
# were decided by these guards must NOT be learned, or the classifier will
# re-learn the keyword-fortress behaviour we just removed.
OLD_GUARD_MARKERS = {
    "news_keyword", "news_guard_respects_local", "weather_keyword_override",
    "clear_news_override", "historical_context_override", "capital_city_guard",
    "astronomy_guard", "literary_context_guard", "creative_content_guard",
    "financial_ephemeral", "current_event_synthesis_override",
    "capability_query_override", "language_translation_override",
    "technical_knowledge_override", "personal_finance_reasoning_override",
}

# Versioning directory
VERSIONS_DIR = ROUTER_DIR / "versions"
VERSIONS_DIR.mkdir(exist_ok=True)

# Max versions to keep (default 5)
MAX_VERSIONS = int(os.environ.get("LUCY_LEARNER_MAX_VERSIONS", "5"))


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


# ---------------------------------------------------------------------------
# Kill switch
# ---------------------------------------------------------------------------


def is_learning_enabled() -> bool:
    """Check if auto-learning is enabled.

    Respects two mechanisms (checked in order):
    1. DISABLE_FLAG file: if `.learner_disable` exists, learning is OFF.
    2. Environment variable: LUCY_AUTO_LEARN=0 disables, anything else enables.

    Returns True if learning may proceed.
    """
    if DISABLE_FLAG.exists():
        return False
    env = os.environ.get("LUCY_AUTO_LEARN", "1").strip().lower()
    return env not in ("0", "false", "no", "off")


def disable_learning(reason: str = "") -> None:
    """Create the disable flag to pause auto-learning."""
    DISABLE_FLAG.write_text(
        f"disabled at {time.strftime('%Y-%m-%d %H:%M:%S')}\nreason: {reason}\n",
        encoding="utf-8",
    )
    print(f"🛑 Auto-learning DISABLED. Reason: {reason or 'manual'}")


def enable_learning() -> None:
    """Remove the disable flag to resume auto-learning."""
    if DISABLE_FLAG.exists():
        DISABLE_FLAG.unlink()
    print("▶️  Auto-learning ENABLED.")


# ---------------------------------------------------------------------------
# Versioning
# ---------------------------------------------------------------------------


def _version_stamp() -> str:
    """Generate a version timestamp string."""
    return time.strftime("%Y%m%d_%H%M%S")


def _rotate_versions():
    """Remove oldest versions if we exceed MAX_VERSIONS."""
    versions = sorted(VERSIONS_DIR.glob("v_*"))
    while len(versions) > MAX_VERSIONS:
        oldest = versions.pop(0)
        # Recursively remove the version directory
        for child in oldest.iterdir():
            child.unlink()
        oldest.rmdir()


def create_version(reason: str = "") -> Path:
    """Snapshot the current index + embeddings + examples as a version.

    Returns the version directory path.
    """
    stamp = _version_stamp()
    vdir = VERSIONS_DIR / f"v_{stamp}"
    vdir.mkdir(exist_ok=True)

    # Copy current artifacts
    for src in (INDEX_PATH, EMBEDDINGS_PATH, EXAMPLES_PATH):
        if src.exists():
            import shutil
            shutil.copy2(str(src), str(vdir / src.name))

    # Metadata
    meta = {
        "timestamp": stamp,
        "reason": reason,
        "example_count": len(load_index()) if INDEX_PATH.exists() else 0,
    }
    with open(vdir / "version.json", "w") as f:
        json.dump(meta, f, indent=2)

    _rotate_versions()
    return vdir


def list_versions() -> list[dict]:
    """List all available versions with metadata."""
    versions = []
    for vdir in sorted(VERSIONS_DIR.glob("v_*")):
        meta_file = vdir / "version.json"
        meta = {}
        if meta_file.exists():
            with open(meta_file) as f:
                meta = json.load(f)
        versions.append({
            "name": vdir.name,
            "path": str(vdir),
            **meta,
        })
    return versions


def rollback_version(version_name: str) -> bool:
    """Restore index + embeddings + examples from a named version.

    Creates a backup of the current state first, then restores.
    Returns True on success.
    """
    vdir = VERSIONS_DIR / version_name
    if not vdir.exists():
        print(f"❌ Version '{version_name}' not found.")
        return False

    # Backup current state before rollback
    backup = create_version(reason=f"pre-rollback-from-{version_name}")
    print(f"  Created pre-rollback backup: {backup.name}")

    # Restore files
    for src_name in (INDEX_PATH.name, EMBEDDINGS_PATH.name, EXAMPLES_PATH.name):
        src = vdir / src_name
        if src.exists():
            dst = ROUTER_DIR / src_name
            import shutil
            shutil.copy2(str(src), str(dst))

    print(f"✅ Rolled back to {version_name}")
    return True


# ---------------------------------------------------------------------------
# Index I/O
# ---------------------------------------------------------------------------


def save_index(examples: list[dict]):
    """Save embedding index atomically."""
    import tempfile
    tmp_dir = str(Path(INDEX_PATH).parent)
    tmp = tempfile.NamedTemporaryFile(
        mode="w", dir=tmp_dir, delete=False,
        prefix=".comprehensive_index.", suffix=".tmp"
    )
    for ex in examples:
        tmp.write(json.dumps(ex) + "\n")
    tmp.close()
    os.replace(tmp.name, INDEX_PATH)


def _strip_example_timestamps(examples: list[dict]) -> list[dict]:
    """Return a copy of examples with runtime timestamps removed.

    Timestamps are mutable runtime metadata. They belong in
    examples_metadata.json, not in the tracked examples file.
    """
    cleaned = []
    for ex in examples:
        copy = dict(ex)
        meta = dict(copy.get("metadata", {}))
        meta.pop("timestamp", None)
        if meta:
            copy["metadata"] = meta
        elif "metadata" in copy:
            del copy["metadata"]
        cleaned.append(copy)
    return cleaned


def rebuild_embeddings(examples: list[dict]):
    """Rebuild embedding matrix from examples."""
    print(f"  Rebuilding embeddings for {len(examples)} examples...")
    router = HybridRouterV2()
    router.fit(examples)
    np.save(EMBEDDINGS_PATH, router.embeddings)

    # Write tracked examples file WITHOUT mutable timestamps
    cleaned = _strip_example_timestamps(router.examples)
    with open(EXAMPLES_PATH, "w") as f:
        json.dump(cleaned, f, indent=2)

    # Write mutable metadata to separate untracked file
    metadata = {
        "last_rebuilt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "example_count": len(router.examples),
        "embedding_shape": list(router.embeddings.shape),
    }
    with open(EXAMPLES_METADATA_PATH, "w") as f:
        json.dump(metadata, f, indent=2)

    print(f"  Saved: {EMBEDDINGS_PATH} ({router.embeddings.shape})")


def deduplicate(examples: list[dict]) -> list[dict]:
    """Remove duplicate queries, keeping the most recent label."""
    seen = {}
    for ex in examples:
        key = ex["query"].lower().strip()
        seen[key] = ex  # Overwrite with latest
    return list(seen.values())


def _load_log_progress() -> int:
    """Return the number of router-log lines already processed."""
    if LOG_PROGRESS_PATH.exists():
        try:
            return int(LOG_PROGRESS_PATH.read_text().strip())
        except ValueError:
            pass
    return 0


def _save_log_progress(count: int) -> None:
    """Persist how many router-log lines have been processed."""
    LOG_PROGRESS_PATH.write_text(str(count))


def _count_new_router_entries(log_path: Path | None) -> int:
    """Count how many router-log entries are new since last learn.

    Mirrors the filters in process_router_logs so the count is accurate.
    """
    if not log_path or not log_path.exists():
        return 0

    already_processed = _load_log_progress()
    count = 0
    line_no = 0

    with open(log_path) as f:
        for line in f:
            line_no += 1
            if line_no <= already_processed:
                continue

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
            if any(j in query.lower() for j in ["test query", "2+2 2+2"]):
                continue
            if len(query) > 150 or query.count("?") > 1:
                continue

            confidence = entry.get("confidence", 0)
            if confidence < 0.7:
                continue

            guards = set(entry.get("guards_fired", []))
            if guards & OLD_GUARD_MARKERS:
                continue

            count += 1

    return count


def process_router_logs(log_path: Path, min_confidence: float = 0.7) -> list[dict]:
    """Process single-path router decision logs and extract learning examples.

    Reads router_decisions.jsonl starting from the last processed position.
    Only high-confidence decisions without old keyword-guard involvement are
    used, to avoid re-learning the keyword-fortress behaviour.
    """
    if not log_path.exists():
        return []

    already_processed = _load_log_progress()
    new_examples = []
    line_no = 0

    with open(log_path) as f:
        for line in f:
            line_no += 1
            if line_no <= already_processed:
                continue

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

            # Skip multi-turn concatenated queries
            if len(query) > 150 or query.count("?") > 1:
                continue

            route = entry.get("route", "")
            confidence = entry.get("confidence", 0)
            intent = entry.get("intent", "local_answer")
            evidence_reason = entry.get("evidence_reason", "")
            guards = set(entry.get("guards_fired", []))

            # Skip entries decided by old keyword guards
            if guards & OLD_GUARD_MARKERS:
                continue

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
                    "guards_fired": list(guards),
                    "embedding_route": entry.get("embedding_route", ""),
                },
            })

    _save_log_progress(line_no)
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
    if not is_learning_enabled():
        if verbose:
            print("🛑 Auto-learning is DISABLED (via .learner_disable or LUCY_AUTO_LEARN=0)")
        return {"status": "disabled", "added": 0}

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

        # Save if new examples were added OR existing entries were modified
        # (e.g. user feedback corrected the route for an existing query)
        index_changed = added > 0 or all_examples != examples
        if index_changed:
            # Snapshot current state before mutation
            vdir = create_version(reason=f"pre-update (+{added} examples)")
            if verbose:
                print(f"  Snapshot created: {vdir.name}")

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
    print(f"  Router log: {log_path}")
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


def maybe_auto_learn(log_path: Path | None = None, min_entries: int | None = None) -> bool:
    """Trigger background learning if enough pending feedback exists.

    Called from execution_engine after writing auto-feedback.
    Runs learning in a background thread to avoid blocking response.

    Args:
        log_path: Router decision log path
        min_entries: Minimum auto-feedback entries to trigger rebuild

    Returns:
        True if learning was triggered, False otherwise
    """
    if not is_learning_enabled():
        return False

    # Separate thresholds: user feedback is high-trust, auto-feedback is low-trust.
    # min_entries parameter overrides user_threshold for backward compatibility.
    user_threshold = (
        min_entries
        if min_entries is not None
        else int(os.environ.get("LUCY_AUTO_LEARN_THRESHOLD", "3"))
    )
    auto_threshold = int(os.environ.get("LUCY_AUTO_FEEDBACK_THRESHOLD", "5"))

    # Default log_path from environment when caller doesn't provide it
    if log_path is None:
        log_dir = os.environ.get("LUCY_ROUTER_LOG_DIR")
        if log_dir:
            log_path = Path(log_dir) / "router_decisions.jsonl"

    sys.path.insert(0, str(ROUTER_DIR))

    # Count auto-feedback if available; don't bail out if the module is missing
    auto_count = 0
    try:
        from auto_feedback import load_auto_feedback
        auto_count = len(load_auto_feedback(min_confidence=0.6))
    except ImportError:
        pass

    # Also count pending user feedback (not just auto-feedback)
    user_count = 0
    if FEEDBACK_PATH.exists():
        with open(FEEDBACK_PATH) as f:
            user_count = sum(1 for line in f if line.strip())

    # Count new router-decision log entries since last learn
    log_count = _count_new_router_entries(log_path)
    log_threshold = int(os.environ.get("LUCY_AUTO_LEARN_LOG_THRESHOLD", "5"))

    # Combined threshold as a fallback (e.g. 3 user + 2 auto = 5)
    combined_threshold = int(
        os.environ.get("LUCY_AUTO_LEARN_THRESHOLD", str(max(user_threshold, auto_threshold)))
    ) if min_entries is None else user_threshold

    # Trigger learning if ANY threshold is met.
    # User feedback is highest-trust, auto-feedback medium, router logs lowest.
    if (
        user_count < user_threshold
        and auto_count < auto_threshold
        and log_count < log_threshold
        and (user_count + auto_count + log_count) < combined_threshold
    ):
        return False

    # Trigger learning in background thread
    import threading
    def _learn():
        try:
            learn_once(log_path, verbose=False)
        except Exception:
            pass

    t = threading.Thread(target=_learn, daemon=True)
    t.start()
    return True


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
    parser.add_argument("--log-path", type=Path, help="Router decision log path (router_decisions.jsonl)")
    parser.add_argument("--feedback", type=str, help="Add user feedback: query string")
    parser.add_argument("--route", type=str, help="Correct route for feedback")
    parser.add_argument("--correct", action="store_true", help="Mark feedback as confirmation (legacy was right)")

    # Kill-switch commands
    parser.add_argument("--disable", action="store_true", help="Pause auto-learning (create .learner_disable)")
    parser.add_argument("--enable", action="store_true", help="Resume auto-learning (remove .learner_disable)")
    parser.add_argument("--status", action="store_true", help="Show learning status (enabled/disabled)")

    # Versioning commands
    parser.add_argument("--snapshot", action="store_true", help="Create a manual snapshot of current index")
    parser.add_argument("--list-versions", action="store_true", help="List all saved versions")
    parser.add_argument("--rollback", type=str, metavar="VERSION", help="Rollback to a named version (e.g., v_20260512_120000)")
    args = parser.parse_args()

    # Kill-switch commands
    if args.disable:
        disable_learning(reason="manual CLI")
        return
    if args.enable:
        enable_learning()
        return
    if args.status:
        enabled = is_learning_enabled()
        print(f"Auto-learning: {'ENABLED' if enabled else 'DISABLED'}")
        if DISABLE_FLAG.exists():
            print(f"  Flag file: {DISABLE_FLAG}")
            print(f"  Content: {DISABLE_FLAG.read_text().strip()}")
        versions = list_versions()
        print(f"  Saved versions: {len(versions)}")
        for v in versions:
            print(f"    {v['name']} — {v.get('example_count', '?')} examples — {v.get('reason', 'no reason')}")
        return

    # Versioning commands
    if args.snapshot:
        vdir = create_version(reason="manual CLI snapshot")
        print(f"✅ Snapshot created: {vdir}")
        return
    if args.list_versions:
        versions = list_versions()
        if not versions:
            print("No versions saved.")
            return
        print(f"{'Name':<25} {'Examples':<10} {'Reason'}")
        print("-" * 60)
        for v in versions:
            print(f"{v['name']:<25} {v.get('example_count', '?'):<10} {v.get('reason', '')}")
        return
    if args.rollback:
        ok = rollback_version(args.rollback)
        sys.exit(0 if ok else 1)

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
