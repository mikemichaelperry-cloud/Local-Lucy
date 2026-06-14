#!/usr/bin/env python3
"""
Append training examples to fix misclassifications from the transcript.

Transcript failures corrected:
  - Triode/electronics queries → LOCAL (general technical knowledge)
  - Capability/translation queries → LOCAL (identity/capability)
  - Meta/system commands → LOCAL (system control)
  - General gardening queries → LOCAL (general knowledge)

Usage:
    python append_transcript_fixes.py --dry-run     # Preview only
    python append_transcript_fixes.py --apply       # Append + rebuild
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROUTER_DIR = Path(__file__).parent.resolve()
INDEX_PATH = ROUTER_DIR / "comprehensive_index.jsonl"
EXAMPLES_PATH = ROUTER_DIR / "comprehensive_examples.json"
EMBEDDINGS_PATH = ROUTER_DIR / "comprehensive_embeddings.npy"
BACKUP_DIR = ROUTER_DIR / "checkpoints"


# ---------------------------------------------------------------------------
# New examples — transcript correction batch
# ---------------------------------------------------------------------------

NEW_EXAMPLES: list[dict] = [
    # ================================================================
    # 1. Electronics / Vacuum Tube Knowledge (LOCAL)
    # Transcript: "Are there any higher gain triodes?" got wrong answer
    # ================================================================
    {
        "query": "Are there any higher gain triodes?",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "transcript_correction", "category": "electronics"},
    },
    {
        "query": "What are some high gain vacuum tubes?",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "transcript_correction", "category": "electronics"},
    },
    {
        "query": "Compare 12AX7 and 6SL7 triodes",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "transcript_correction", "category": "electronics"},
    },
    {
        "query": "What is the amplification factor of a 12AX7?",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "transcript_correction", "category": "electronics"},
    },
    {
        "query": "Best triodes for guitar preamps",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "transcript_correction", "category": "electronics"},
    },
    {
        "query": "What is the difference between a triode and a tetrode?",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "transcript_correction", "category": "electronics"},
    },
    {
        "query": "List common high-mu triodes",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "transcript_correction", "category": "electronics"},
    },

    # ================================================================
    # 2. Capability / Translation Queries (LOCAL)
    # Transcript: "Are you capable of Hebrew to English translation?"
    # got denial. Capability questions should route to LOCAL.
    # ================================================================
    {
        "query": "Are you capable of Hebrew to English translation?",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "transcript_correction", "category": "capability"},
    },
    {
        "query": "Can you translate from Hebrew?",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "transcript_correction", "category": "capability"},
    },
    {
        "query": "Do you speak Hebrew?",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "transcript_correction", "category": "capability"},
    },
    {
        "query": "Translate this Hebrew text for me",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "transcript_correction", "category": "capability"},
    },
    {
        "query": "Can you do language translation?",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "transcript_correction", "category": "capability"},
    },
    {
        "query": "Are you able to translate Arabic?",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "transcript_correction", "category": "capability"},
    },
    {
        "query": "What languages can you translate?",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "transcript_correction", "category": "capability"},
    },

    # ================================================================
    # 3. Meta / System Commands (LOCAL)
    # Transcript: "Use Augmented mode" and "Try all Augmented providers"
    # got hallucinated response about starship fuel.
    # These are system control queries and should stay LOCAL.
    # ================================================================
    {
        "query": "Use Augmented mode",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "transcript_correction", "category": "meta_command"},
    },
    {
        "query": "Try all Augmented providers",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "transcript_correction", "category": "meta_command"},
    },
    {
        "query": "Switch to augmented mode",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "transcript_correction", "category": "meta_command"},
    },
    {
        "query": "Enable augmented providers",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "transcript_correction", "category": "meta_command"},
    },
    {
        "query": "What providers are available?",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "transcript_correction", "category": "meta_command"},
    },
    {
        "query": "Show me the available modes",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "transcript_correction", "category": "meta_command"},
    },
    {
        "query": "Change to local mode",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "transcript_correction", "category": "meta_command"},
    },

    # ================================================================
    # 4. General Knowledge / Gardening (LOCAL)
    # Transcript: "What is the best general purpose fertilizer for lawns?"
    # was answered correctly but we ensure it stays LOCAL.
    # ================================================================
    {
        "query": "What is the best general purpose fertilizer for lawns?",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "transcript_correction", "category": "general_knowledge"},
    },
    {
        "query": "What are the exact ingredients in lawn fertilizer?",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "transcript_correction", "category": "general_knowledge"},
    },
    {
        "query": "16-4-8 fertilizer ingredients",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "transcript_correction", "category": "general_knowledge"},
    },
    {
        "query": "How does NPK fertilizer work?",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "transcript_correction", "category": "general_knowledge"},
    },

    # ================================================================
    # 5. Adversarial variants (common misphrasings)
    # ================================================================
    {
        "query": "Any higher gain triodes out there?",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "transcript_correction", "category": "electronics"},
    },
    {
        "query": "Can you translate Hebrew to English?",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "transcript_correction", "category": "capability"},
    },
    {
        "query": "Turn on augmented mode",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "transcript_correction", "category": "meta_command"},
    },
    {
        "query": "List all augmented providers",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "transcript_correction", "category": "meta_command"},
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_existing_queries() -> set[str]:
    """Load existing queries for deduplication from canonical JSON."""
    existing: set[str] = set()

    if EXAMPLES_PATH.exists():
        with open(EXAMPLES_PATH, encoding="utf-8") as f:
            try:
                examples = json.load(f)
                for ex in examples:
                    existing.add(ex.get("query", "").lower().strip())
            except (json.JSONDecodeError, TypeError):
                pass

    return existing


def backup_files():
    """Create timestamped backups of canonical examples and embeddings."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    if EXAMPLES_PATH.exists():
        shutil.copy2(EXAMPLES_PATH, BACKUP_DIR / f"comprehensive_examples_{ts}.json")
    if EMBEDDINGS_PATH.exists():
        shutil.copy2(EMBEDDINGS_PATH, BACKUP_DIR / f"comprehensive_embeddings_{ts}.npy")

    print(f"Backups created in {BACKUP_DIR}/")
    return ts


def append_to_examples(new_examples: list[dict]):
    """Append new examples to the canonical JSON file."""
    examples = []
    if EXAMPLES_PATH.exists():
        with open(EXAMPLES_PATH, encoding="utf-8") as f:
            examples = json.load(f)
    examples.extend(new_examples)
    with open(EXAMPLES_PATH, "w", encoding="utf-8") as f:
        json.dump(examples, f, indent=2, ensure_ascii=False)
    print(f"Appended {len(new_examples)} examples to {EXAMPLES_PATH} (total {len(examples)})")


def rebuild_embeddings():
    """Trigger embedding rebuild."""
    rebuild_script = Path(__file__).parent.parent.parent / "scripts" / "rebuild_embeddings.py"
    if rebuild_script.exists():
        import subprocess
        result = subprocess.run(
            [sys.executable, str(rebuild_script)],
            capture_output=True,
            text=True,
        )
        print(result.stdout)
        if result.returncode != 0:
            print(f"WARNING: rebuild failed:\n{result.stderr}")
            return False
        return True
    else:
        print(f"WARNING: rebuild_embeddings.py not found at {rebuild_script}")
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Append transcript correction examples to embedding index")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, do not modify files")
    parser.add_argument("--apply", action="store_true", help="Append examples and rebuild embeddings")
    args = parser.parse_args()

    existing = load_existing_queries()
    print(f"Existing examples: {len(existing)}")

    # Filter out duplicates
    new_examples = []
    for ex in NEW_EXAMPLES:
        norm = ex["query"].lower().strip()
        if norm not in existing:
            new_examples.append(ex)
        else:
            print(f"  SKIP (duplicate): {ex['query'][:60]}")

    if not new_examples:
        print("\n✅ All examples already exist in the index. Nothing to add.")
        return

    # Stats
    by_route = Counter(ex["labels"]["route"] for ex in new_examples)
    by_category = Counter(ex["metadata"]["category"] for ex in new_examples)

    print(f"\nNew examples to add: {len(new_examples)}")
    print(f"By route:")
    for route, count in sorted(by_route.items()):
        print(f"  {route:12s} {count:2d}")
    print(f"By category:")
    for cat, count in sorted(by_category.items()):
        print(f"  {cat:15s} {count:2d}")

    if args.dry_run or not args.apply:
        print(f"\n💡 Use --apply to append and rebuild")
        return

    # Apply
    print(f"\n⚠️  Applying changes in 3 seconds... (Ctrl+C to cancel)")
    import time
    try:
        time.sleep(3)
    except KeyboardInterrupt:
        print("\nCancelled.")
        return

    backup_files()
    append_to_examples(new_examples)
    rebuild_embeddings()

    print(f"\n✅ Done! Index now has {len(existing) + len(new_examples)} examples")


if __name__ == "__main__":
    main()
