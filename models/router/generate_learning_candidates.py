#!/usr/bin/env python3
"""
Generate learning candidates from usage data for manual review.

This script mines router decision logs, feedback buffers, user corrections,
and auto-feedback to produce candidate training examples. It is READ-ONLY
on production files by default — it outputs a reviewable JSONL file that
can be inspected before merging into the embedding index.

Usage:
    # Dry run — show what would be generated (default)
    python generate_learning_candidates.py

    # Write candidates to file for review
    python generate_learning_candidates.py --output candidates_2026-05-10.jsonl

    # Apply candidates via background_learner.py (after review)
    python generate_learning_candidates.py --apply

Safety:
    - Never modifies comprehensive_examples.json
      unless --apply is explicitly passed.
    - Deduplicates against existing examples.
    - Filters test/junk queries.
    - Tracks provenance for every candidate.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROUTER_DIR = Path(__file__).parent.resolve()
INDEX_PATH = ROUTER_DIR / "comprehensive_index.jsonl"
EXAMPLES_PATH = ROUTER_DIR / "comprehensive_examples.json"

DEFAULT_ROUTER_LOG_DIR = os.environ.get("LUCY_ROUTER_LOG_DIR", "")
ROUTER_LOG_PATH = (
    Path(DEFAULT_ROUTER_LOG_DIR) / "router_decisions.jsonl" if DEFAULT_ROUTER_LOG_DIR else None
)

RUNTIME_NS = Path(
    os.environ.get(
        "LUCY_RUNTIME_NAMESPACE_ROOT",
        str(Path.home() / ".codex-api-home" / "lucy" / "runtime-v10"),
    )
)
FEEDBACK_BUFFER_PATH = RUNTIME_NS / "feedback_buffer.json"
USER_FEEDBACK_PATH = ROUTER_DIR / "user_feedback.jsonl"
AUTO_FEEDBACK_PATH = ROUTER_DIR / "auto_feedback.jsonl"

# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

_TEST_JUNK_PATTERNS = [
    "test query",
    "2+2 2+2",
    "word word word",
    "<script>",
    "lorem ipsum",
    "aaaaaaaaaa",
    "bbbbbbbbbb",
]

_MIN_QUERY_LENGTH = 3
_MAX_QUERY_LENGTH = 500

# Confidence thresholds
_MIN_LOG_CONFIDENCE = 0.70  # Only learn from confident router decisions
_MIN_FEEDBACK_CONFIDENCE = 0.60  # Auto-feedback minimum
_MIN_LOW_CONFIDENCE = 0.40  # Below this = needs more examples

# Routes that are valid for training
_VALID_ROUTES = {
    "LOCAL",
    "AUGMENTED",
    "NEWS",
    "TIME",
    "WEATHER",
    "EPHEMERAL",
    "CLARIFY",
    "SELF_REVIEW",
}


def _is_test_or_junk(query: str) -> bool:
    """Filter out test queries and junk."""
    if not query:
        return True
    q_lower = query.lower().strip()
    if len(q_lower) < _MIN_QUERY_LENGTH:
        return True
    if len(q_lower) > _MAX_QUERY_LENGTH:
        return True
    return any(p in q_lower for p in _TEST_JUNK_PATTERNS)


def _normalize_query(query: str) -> str:
    """Normalize query for deduplication."""
    return query.lower().strip()


# ---------------------------------------------------------------------------
# Loaders (all read-only)
# ---------------------------------------------------------------------------


def load_existing_queries() -> set[str]:
    """Load all existing queries from the canonical JSON for deduplication."""
    existing: set[str] = set()

    if EXAMPLES_PATH.exists():
        with open(EXAMPLES_PATH, encoding="utf-8") as f:
            try:
                examples = json.load(f)
                for ex in examples:
                    existing.add(_normalize_query(ex.get("query", "")))
            except (json.JSONDecodeError, TypeError):
                pass

    return existing


def load_router_logs(log_path: Path | None) -> list[dict]:
    """Load router decision logs."""
    if not log_path or not log_path.exists():
        return []

    entries = []
    with open(log_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def load_feedback_buffer() -> list[dict]:
    """Load feedback buffer exchanges."""
    if not FEEDBACK_BUFFER_PATH.exists():
        return []

    try:
        with open(FEEDBACK_BUFFER_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("exchanges", [])
    except (json.JSONDecodeError, OSError):
        return []


def load_user_feedback() -> list[dict]:
    """Load explicit user feedback corrections."""
    if not USER_FEEDBACK_PATH.exists():
        return []

    entries = []
    with open(USER_FEEDBACK_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def load_auto_feedback() -> list[dict]:
    """Load auto-feedback misroute detections."""
    if not AUTO_FEEDBACK_PATH.exists():
        return []

    entries = []
    with open(AUTO_FEEDBACK_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


# ---------------------------------------------------------------------------
# Candidate generators
# ---------------------------------------------------------------------------


def candidates_from_router_logs(entries: list[dict], existing: set[str]) -> list[dict]:
    """
    Extract candidates from router decision logs.

    High-signal cases:
    1. Memory gate override — embedding router chose wrong route, memory gate fixed it.
       The final (corrected) route is the label.
    2. Guard disagreement — embedding and legacy chose different routes.
       Indicates an ambiguous query that needs more examples.
    3. Low-confidence decisions — confidence < 0.40 needs reinforcement.
    4. High-confidence correct decisions — confidence >= 0.85 with no overrides.
       These are "known good" examples that reinforce the current behavior.
    """
    candidates = []
    seen_queries: set[str] = set()

    for entry in entries:
        query = entry.get("query", "").strip()
        if _is_test_or_junk(query):
            continue

        norm = _normalize_query(query)
        if norm in existing or norm in seen_queries:
            continue
        seen_queries.add(norm)

        route = entry.get("route", "")
        embedding_route = entry.get("embedding_route", route)
        confidence = entry.get("confidence", 0.0)
        intent = entry.get("intent", "local_answer")
        guards_fired = entry.get("guards_fired", [])
        legacy_agrees = entry.get("legacy_agrees", True)
        memory_gate_override = entry.get("memory_gate_override", "")
        evidence_reason = entry.get("evidence_reason", "")

        if route not in _VALID_ROUTES:
            continue

        # Signal 1: Memory gate override (strongest signal)
        if memory_gate_override and embedding_route != route:
            evidence = "required" if evidence_reason else "not_required"
            candidates.append(
                {
                    "query": query,
                    "labels": {
                        "intent_family": intent,
                        "evidence_mode": evidence,
                        "route": route,
                        "policy_override": "none",
                    },
                    "metadata": {
                        "source": "router_log_memory_gate",
                        "confidence": confidence,
                        "embedding_route": embedding_route,
                        "guards_fired": guards_fired,
                        "reason": f"memory_gate_override: {embedding_route} -> {route}",
                    },
                }
            )
            continue

        # Signal 2: Guard disagreement (embedding vs legacy disagree)
        if not legacy_agrees and confidence >= 0.5:
            evidence = "required" if evidence_reason else "not_required"
            candidates.append(
                {
                    "query": query,
                    "labels": {
                        "intent_family": intent,
                        "evidence_mode": evidence,
                        "route": route,
                        "policy_override": "none",
                    },
                    "metadata": {
                        "source": "router_log_guard_disagreement",
                        "confidence": confidence,
                        "legacy_route": entry.get("legacy_route_audit", ""),
                        "reason": "embedding and legacy keyword router disagreed",
                    },
                }
            )
            continue

        # Signal 3: Low confidence — needs reinforcement
        if confidence < _MIN_LOW_CONFIDENCE:
            evidence = "required" if evidence_reason else "not_required"
            candidates.append(
                {
                    "query": query,
                    "labels": {
                        "intent_family": intent,
                        "evidence_mode": evidence,
                        "route": route,
                        "policy_override": "none",
                    },
                    "metadata": {
                        "source": "router_log_low_confidence",
                        "confidence": confidence,
                        "reason": f"low confidence ({confidence:.2f}) needs reinforcement",
                    },
                }
            )
            continue

        # Signal 4: High-confidence known-good
        if confidence >= 0.85 and not guards_fired:
            evidence = "required" if evidence_reason else "not_required"
            candidates.append(
                {
                    "query": query,
                    "labels": {
                        "intent_family": intent,
                        "evidence_mode": evidence,
                        "route": route,
                        "policy_override": "none",
                    },
                    "metadata": {
                        "source": "router_log_confirmed",
                        "confidence": confidence,
                        "reason": "high-confidence decision with no guard overrides",
                    },
                }
            )

    return candidates


def candidates_from_feedback_buffer(exchanges: list[dict], existing: set[str]) -> list[dict]:
    """
    Extract candidates from feedback buffer.

    The feedback buffer stores recent exchanges. We treat each unique query
    as a candidate if it hasn't been seen before. This injects diversity
    into the embedding space by covering the user's actual query distribution.
    """
    candidates = []
    seen_queries: set[str] = set()

    for entry in exchanges:
        query = entry.get("query", "").strip()
        if _is_test_or_junk(query):
            continue

        norm = _normalize_query(query)
        if norm in existing or norm in seen_queries:
            continue
        seen_queries.add(norm)

        route = entry.get("route", "")
        intent = entry.get("intent_family", "local_answer")
        confidence = entry.get("confidence", 0.0)

        if route not in _VALID_ROUTES:
            continue

        # Skip empty queries
        if not query:
            continue

        evidence = "required" if route == "AUGMENTED" else "not_required"

        candidates.append(
            {
                "query": query,
                "labels": {
                    "intent_family": intent,
                    "evidence_mode": evidence,
                    "route": route,
                    "policy_override": "none",
                },
                "metadata": {
                    "source": "feedback_buffer",
                    "confidence": confidence,
                    "reason": "real user query from feedback buffer",
                },
            }
        )

    return candidates


def candidates_from_user_feedback(entries: list[dict], existing: set[str]) -> list[dict]:
    """
    Extract candidates from explicit user feedback.

    These are the strongest signals — the user explicitly told us the
    correct route.
    """
    candidates = []
    seen_queries: set[str] = set()

    for entry in entries:
        query = entry.get("query", "").strip()
        if _is_test_or_junk(query):
            continue

        norm = _normalize_query(query)
        if norm in existing or norm in seen_queries:
            continue
        seen_queries.add(norm)

        correct_route = entry.get("correct_route", "")
        if correct_route not in _VALID_ROUTES:
            continue

        feedback_type = entry.get("feedback_type", "correction")
        evidence = "required" if correct_route == "AUGMENTED" else "not_required"

        # Map route to intent family
        intent_map = {
            "LOCAL": "local_answer",
            "AUGMENTED": "current_evidence",
            "NEWS": "news_request",
            "TIME": "time_query",
            "WEATHER": "ephemeral_query",
        }
        intent = intent_map.get(correct_route, "local_answer")

        candidates.append(
            {
                "query": query,
                "labels": {
                    "intent_family": intent,
                    "evidence_mode": evidence,
                    "route": correct_route,
                    "policy_override": "none",
                },
                "metadata": {
                    "source": "user_feedback",
                    "feedback_type": feedback_type,
                    "timestamp": entry.get("timestamp", ""),
                    "reason": f"explicit user {feedback_type}",
                },
            }
        )

    return candidates


def candidates_from_auto_feedback(entries: list[dict], existing: set[str]) -> list[dict]:
    """
    Extract candidates from auto-feedback (answer quality analysis).

    Auto-feedback detects misroutes by analyzing the response text.
    High-confidence detections (> 0.7) are strong signals.
    """
    candidates = []
    seen_queries: set[str] = set()

    for entry in entries:
        query = entry.get("query", "").strip()
        if _is_test_or_junk(query):
            continue

        norm = _normalize_query(query)
        if norm in existing or norm in seen_queries:
            continue
        seen_queries.add(norm)

        confidence = entry.get("confidence", 0.0)
        if confidence < _MIN_FEEDBACK_CONFIDENCE:
            continue

        correct_route = entry.get("correct_route", "")
        if correct_route not in _VALID_ROUTES:
            continue

        evidence = "required" if correct_route == "AUGMENTED" else "not_required"
        intent_map = {
            "LOCAL": "local_answer",
            "AUGMENTED": "current_evidence",
            "NEWS": "news_request",
            "TIME": "time_query",
            "WEATHER": "ephemeral_query",
        }
        intent = intent_map.get(correct_route, "local_answer")

        candidates.append(
            {
                "query": query,
                "labels": {
                    "intent_family": intent,
                    "evidence_mode": evidence,
                    "route": correct_route,
                    "policy_override": "none",
                },
                "metadata": {
                    "source": "auto_feedback",
                    "confidence": confidence,
                    "auto_reason": entry.get("reason", ""),
                    "details": entry.get("details", ""),
                    "reason": f"auto-detected misroute ({entry.get('reason', '')})",
                },
            }
        )

    return candidates


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------


def generate_candidates(
    log_path: Path | None,
    since: datetime | None = None,
) -> tuple[list[dict], dict[str, Any]]:
    """Generate all candidates and return stats."""
    print("Loading existing examples for deduplication...")
    existing = load_existing_queries()
    print(f"  {len(existing)} existing queries in index")

    # Load all data sources
    router_logs = load_router_logs(log_path)
    feedback_buffer = load_feedback_buffer()
    user_feedback = load_user_feedback()
    auto_feedback = load_auto_feedback()

    print("\nData sources found:")
    print(f"  Router decision logs: {len(router_logs)} entries")
    print(f"  Feedback buffer:      {len(feedback_buffer)} exchanges")
    print(f"  User feedback:        {len(user_feedback)} corrections")
    print(f"  Auto-feedback:        {len(auto_feedback)} detections")

    # Optional time filtering
    if since:
        router_logs = [
            e
            for e in router_logs
            if _parse_timestamp(e.get("timestamp", "")) is None
            or _parse_timestamp(e.get("timestamp", "")) >= since
        ]
        feedback_buffer = [
            e
            for e in feedback_buffer
            if _parse_timestamp(e.get("timestamp", "")) is None
            or _parse_timestamp(e.get("timestamp", "")) >= since
        ]
        user_feedback = [
            e
            for e in user_feedback
            if _parse_timestamp(e.get("timestamp", "")) is None
            or _parse_timestamp(e.get("timestamp", "")) >= since
        ]
        auto_feedback = [
            e
            for e in auto_feedback
            if _parse_timestamp(e.get("timestamp", "")) is None
            or _parse_timestamp(e.get("timestamp", "")) >= since
        ]
        print(f"\nAfter time filter (since {since.isoformat()}):")
        print(f"  Router logs: {len(router_logs)}")
        print(f"  Feedback buffer: {len(feedback_buffer)}")
        print(f"  User feedback: {len(user_feedback)}")
        print(f"  Auto feedback: {len(auto_feedback)}")

    # Generate candidates from each source
    c_logs = candidates_from_router_logs(router_logs, existing)
    c_buffer = candidates_from_feedback_buffer(feedback_buffer, existing)
    c_user = candidates_from_user_feedback(user_feedback, existing)
    c_auto = candidates_from_auto_feedback(auto_feedback, existing)

    # Deduplicate across sources (user feedback > auto feedback > router logs > buffer)
    all_candidates = []
    seen: set[str] = set()

    for source_list, source_name in [
        (c_user, "user_feedback"),
        (c_auto, "auto_feedback"),
        (c_logs, "router_logs"),
        (c_buffer, "feedback_buffer"),
    ]:
        for cand in source_list:
            norm = _normalize_query(cand["query"])
            if norm not in seen:
                seen.add(norm)
                all_candidates.append(cand)

    # Stats
    source_counts = Counter(c["metadata"]["source"] for c in all_candidates)
    route_counts = Counter(c["labels"]["route"] for c in all_candidates)

    stats = {
        "existing_queries": len(existing),
        "router_logs_read": len(router_logs),
        "feedback_buffer_read": len(feedback_buffer),
        "user_feedback_read": len(user_feedback),
        "auto_feedback_read": len(auto_feedback),
        "candidates_generated": len(all_candidates),
        "by_source": dict(source_counts),
        "by_route": dict(route_counts),
    }

    return all_candidates, stats


def _parse_timestamp(ts: str) -> datetime | None:
    """Parse ISO timestamp string."""
    if not ts:
        return None
    try:
        # Handle both +00:00 and Z suffixes
        ts = ts.replace("Z", "+00:00")
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def print_stats(stats: dict[str, Any]) -> None:
    """Print candidate generation statistics."""
    print("\n" + "=" * 60)
    print("Candidate Generation Summary")
    print("=" * 60)
    print(f"Existing queries in index:  {stats['existing_queries']}")
    print(f"Router logs scanned:        {stats['router_logs_read']}")
    print(f"Feedback buffer scanned:    {stats['feedback_buffer_read']}")
    print(f"User feedback scanned:      {stats['user_feedback_read']}")
    print(f"Auto-feedback scanned:      {stats['auto_feedback_read']}")
    print(f"\nCandidates generated:       {stats['candidates_generated']}")

    if stats["by_source"]:
        print("\nBy source:")
        for source, count in sorted(stats["by_source"].items(), key=lambda x: -x[1]):
            print(f"  {source:25s} {count:4d}")

    if stats["by_route"]:
        print("\nBy route:")
        for route, count in sorted(stats["by_route"].items(), key=lambda x: -x[1]):
            print(f"  {route:12s} {count:4d}")


def apply_candidates(candidates: list[dict]) -> None:
    """Delegate to background_learner.py to apply candidates."""
    learner_path = ROUTER_DIR / "background_learner.py"
    if not learner_path.exists():
        print(f"ERROR: background_learner.py not found at {learner_path}")
        sys.exit(1)

    # Write candidates to the learned_examples.jsonl path that background_learner
    # expects, then trigger a learn cycle
    learned_path = ROUTER_DIR / "learned_examples.jsonl"
    with open(learned_path, "w", encoding="utf-8") as f:
        for cand in candidates:
            f.write(json.dumps(cand) + "\n")

    print(f"\nWrote {len(candidates)} candidates to {learned_path}")
    print("Triggering background_learner.py --process...")

    import subprocess

    result = subprocess.run(
        [sys.executable, str(learner_path), "--process"],
        capture_output=True,
        text=True,
    )
    print(result.stdout)
    if result.returncode != 0:
        print(f"ERROR: background_learner failed:\n{result.stderr}")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate learning candidates from usage data for review",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write candidates to this JSONL file (default: stdout in dry-run mode)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply candidates via background_learner.py (DANGEROUS — review first!)",
    )
    parser.add_argument(
        "--log-path",
        type=Path,
        help="Path to router_decisions.jsonl (default: $LUCY_ROUTER_LOG_DIR/router_decisions.jsonl)",
    )
    parser.add_argument(
        "--since",
        type=str,
        help="Only process entries after this ISO date (e.g., 2026-05-01)",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=0,
        help="Only output top N candidates (0 = all)",
    )
    args = parser.parse_args()

    # Determine log path
    log_path = args.log_path
    if not log_path and ROUTER_LOG_PATH and ROUTER_LOG_PATH.exists():
        log_path = ROUTER_LOG_PATH

    # Parse since date
    since = None
    if args.since:
        try:
            since = datetime.fromisoformat(args.since)
        except ValueError:
            print(f"ERROR: Invalid --since date: {args.since}")
            sys.exit(1)

    # Generate candidates
    candidates, stats = generate_candidates(log_path, since)
    print_stats(stats)

    if not candidates:
        print("\n✅ No new candidates found. Index is up to date.")
        return

    # Sort by signal strength (user feedback > auto > router logs > buffer)
    source_priority = {
        "user_feedback": 0,
        "auto_feedback": 1,
        "router_log_memory_gate": 2,
        "router_log_guard_disagreement": 3,
        "router_log_low_confidence": 4,
        "router_log_confirmed": 5,
        "feedback_buffer": 6,
    }
    candidates.sort(key=lambda c: source_priority.get(c["metadata"]["source"], 99))

    # Limit if requested
    if args.top > 0:
        candidates = candidates[: args.top]
        print(f"\nLimited to top {args.top} candidates.")

    # Apply or output
    if args.apply:
        print("\n⚠️  --apply passed: this will modify the embedding index!")
        print("   Press Ctrl+C within 3 seconds to cancel...")
        try:
            import time

            time.sleep(3)
        except KeyboardInterrupt:
            print("\nCancelled.")
            return
        apply_candidates(candidates)
    else:
        # Dry run — output candidates
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                for cand in candidates:
                    f.write(json.dumps(cand) + "\n")
            print(f"\n💾 Wrote {len(candidates)} candidates to {args.output}")
            print(f"   Review with: cat {args.output} | python3 -m json.tool --compact")
            print(f"   Then apply with: python {Path(__file__).name} --apply")
        else:
            print("\n📋 Candidate preview (first 5):")
            for cand in candidates[:5]:
                print(f"\n  Query:    {cand['query'][:80]}")
                print(f"  Route:    {cand['labels']['route']}")
                print(f"  Source:   {cand['metadata']['source']}")
                print(f"  Reason:   {cand['metadata']['reason']}")
            if len(candidates) > 5:
                print(f"\n  ... and {len(candidates) - 5} more")
            print("\n💡 Use --output FILE.jsonl to save, then review before applying.")


if __name__ == "__main__":
    main()
