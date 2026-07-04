#!/usr/bin/env python3
"""Append Hebrew training examples to the router dataset.

Hebrew is a first-class user language for Local Lucy. These examples ensure the
embedding router and route labels treat Hebrew queries the same way as their
English equivalents, rather than falling back to a default because the model has
not seen Hebrew before.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROUTER_DIR = Path(__file__).parent.resolve()
INDEX_PATH = ROUTER_DIR / "comprehensive_index.jsonl"
EXAMPLES_PATH = ROUTER_DIR / "comprehensive_examples.json"
EMBEDDINGS_PATH = ROUTER_DIR / "comprehensive_embeddings.npy"
BACKUP_DIR = ROUTER_DIR / "checkpoints"

NEW_EXAMPLES: list[dict] = [
    # --- LOCAL (general knowledge, personal, creative, opinion) ---
    {
        "query": "מה השם שלך?",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "hebrew_first_class", "category": "identity_local"},
    },
    {
        "query": "מי את?",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "hebrew_first_class", "category": "identity_local"},
    },
    {
        "query": "מה אתה יכול לעשות?",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "hebrew_first_class", "category": "capabilities"},
    },
    {
        "query": "ספר לי בדיחה",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "hebrew_first_class", "category": "creative"},
    },
    {
        "query": "כתוב לי סיפור קצר",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "hebrew_first_class", "category": "creative"},
    },
    {
        "query": "מהי דעתך על בינה מלאכותית?",
        "labels": {"intent_family": "local_reasoning", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "hebrew_first_class", "category": "opinion"},
    },
    {
        "query": "איך מותקנים פייתון?",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "hebrew_first_class", "category": "howto"},
    },
    {
        "query": "תרגום של שלום לאנגלית",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "hebrew_first_class", "category": "translation"},
    },
    {
        "query": "מה ההבדל בין קטן לגדול?",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "hebrew_first_class", "category": "general"},
    },
    {
        "query": "מי הילדים שלי?",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "hebrew_first_class", "category": "personal_family"},
    },
    {
        "query": "כמה ילדים יש לי?",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "hebrew_first_class", "category": "personal_family"},
    },
    {
        "query": "ספר לי על הכלב שלי",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "hebrew_first_class", "category": "personal_family"},
    },
    # --- AUGMENTED (factual lookups) ---
    {
        "query": "מהי עיר הבירה של צרפת?",
        "labels": {"intent_family": "factual_lookup", "evidence_mode": "not_required", "route": "AUGMENTED", "policy_override": "none"},
        "metadata": {"source": "hebrew_first_class", "category": "factual_lookup"},
    },
    {
        "query": "מי היה אדם הראשון שטס לחלל?",
        "labels": {"intent_family": "factual_lookup", "evidence_mode": "not_required", "route": "AUGMENTED", "policy_override": "none"},
        "metadata": {"source": "hebrew_first_class", "category": "factual_lookup"},
    },
    {
        "query": "מה גובהו של הר אוורסט?",
        "labels": {"intent_family": "factual_lookup", "evidence_mode": "not_required", "route": "AUGMENTED", "policy_override": "none"},
        "metadata": {"source": "hebrew_first_class", "category": "factual_lookup"},
    },
    {
        "query": "מהי משמעות החיים?",
        "labels": {"intent_family": "factual_lookup", "evidence_mode": "not_required", "route": "AUGMENTED", "policy_override": "none"},
        "metadata": {"source": "hebrew_first_class", "category": "factual_lookup"},
    },
    {
        "query": "תן לי מידע על קיבוץ מגל",
        "labels": {"intent_family": "specific_entity_fact", "evidence_mode": "not_required", "route": "AUGMENTED", "policy_override": "none"},
        "metadata": {"source": "hebrew_first_class", "category": "specific_entity"},
    },
    # --- EVIDENCE (medical / vet / legal) ---
    {
        "query": "הכלב שלי מקיא, מה לעשות?",
        "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "EVIDENCE", "policy_override": "none"},
        "metadata": {"source": "hebrew_first_class", "category": "veterinary"},
    },
    {
        "query": "החתול שלי לא אוכל כבר יומיים",
        "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "EVIDENCE", "policy_override": "none"},
        "metadata": {"source": "hebrew_first_class", "category": "veterinary"},
    },
    {
        "query": "האם כלבים יכולים לאכול שוקולד?",
        "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "EVIDENCE", "policy_override": "none"},
        "metadata": {"source": "hebrew_first_class", "category": "veterinary"},
    },
    {
        "query": "כאב בטן חזק וחום מה לעשות?",
        "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "EVIDENCE", "policy_override": "none"},
        "metadata": {"source": "hebrew_first_class", "category": "medical"},
    },
    {
        "query": "מהן תופעות הלוואי של אספירין?",
        "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "EVIDENCE", "policy_override": "none"},
        "metadata": {"source": "hebrew_first_class", "category": "medical"},
    },
    {
        "query": "האם חיסונים לילדים בטוחים?",
        "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "EVIDENCE", "policy_override": "none"},
        "metadata": {"source": "hebrew_first_class", "category": "medical"},
    },
    {
        "query": "מהו היסוד הנפשי בפלילים?",
        "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "EVIDENCE", "policy_override": "none"},
        "metadata": {"source": "hebrew_first_class", "category": "legal"},
    },
    # --- NEWS ---
    {
        "query": "מהן חדשות היום?",
        "labels": {"intent_family": "current_news", "evidence_mode": "not_required", "route": "NEWS", "policy_override": "none"},
        "metadata": {"source": "hebrew_first_class", "category": "news"},
    },
    {
        "query": "ספר לי על האירועים האחרונים בישראל",
        "labels": {"intent_family": "current_news", "evidence_mode": "not_required", "route": "NEWS", "policy_override": "none"},
        "metadata": {"source": "hebrew_first_class", "category": "news"},
    },
    {
        "query": "מה קורה בעולם?",
        "labels": {"intent_family": "current_news", "evidence_mode": "not_required", "route": "NEWS", "policy_override": "none"},
        "metadata": {"source": "hebrew_first_class", "category": "news"},
    },
    {
        "query": "חדשות עדכניות על טכנולוגיה",
        "labels": {"intent_family": "current_news", "evidence_mode": "not_required", "route": "NEWS", "policy_override": "none"},
        "metadata": {"source": "hebrew_first_class", "category": "news"},
    },
    # --- WEATHER ---
    {
        "query": "מה מזג האוויר היום?",
        "labels": {"intent_family": "current_weather", "evidence_mode": "not_required", "route": "WEATHER", "policy_override": "none"},
        "metadata": {"source": "hebrew_first_class", "category": "weather"},
    },
    {
        "query": "האם ירד גשם מחר בתל אביב?",
        "labels": {"intent_family": "current_weather", "evidence_mode": "not_required", "route": "WEATHER", "policy_override": "none"},
        "metadata": {"source": "hebrew_first_class", "category": "weather"},
    },
    {
        "query": "מה הטמפרטורה בירושלים?",
        "labels": {"intent_family": "current_weather", "evidence_mode": "not_required", "route": "WEATHER", "policy_override": "none"},
        "metadata": {"source": "hebrew_first_class", "category": "weather"},
    },
    # --- TIME ---
    {
        "query": "מה השעה עכשיו?",
        "labels": {"intent_family": "current_time", "evidence_mode": "not_required", "route": "TIME", "policy_override": "none"},
        "metadata": {"source": "hebrew_first_class", "category": "time"},
    },
    {
        "query": "מה השעה בניו יורק?",
        "labels": {"intent_family": "current_time", "evidence_mode": "not_required", "route": "TIME", "policy_override": "none"},
        "metadata": {"source": "hebrew_first_class", "category": "time"},
    },
    {
        "query": "מתי השעון מתקדם?",
        "labels": {"intent_family": "current_time", "evidence_mode": "not_required", "route": "TIME", "policy_override": "none"},
        "metadata": {"source": "hebrew_first_class", "category": "time"},
    },
    # --- FINANCE ---
    {
        "query": "מה מחיר המניה של אפל?",
        "labels": {"intent_family": "current_finance", "evidence_mode": "not_required", "route": "FINANCE", "policy_override": "none"},
        "metadata": {"source": "hebrew_first_class", "category": "finance"},
    },
    {
        "query": "מה מחיר הביטקוין?",
        "labels": {"intent_family": "current_finance", "evidence_mode": "not_required", "route": "FINANCE", "policy_override": "none"},
        "metadata": {"source": "hebrew_first_class", "category": "finance"},
    },
    {
        "query": "כמה שווה הדולר היום?",
        "labels": {"intent_family": "current_finance", "evidence_mode": "not_required", "route": "FINANCE", "policy_override": "none"},
        "metadata": {"source": "hebrew_first_class", "category": "finance"},
    },
    # --- EPHEMERAL (transient / time-sensitive non-news) ---
    {
        "query": "מי מנצח במשחק עכשיו?",
        "labels": {"intent_family": "ephemeral", "evidence_mode": "not_required", "route": "EPHEMERAL", "policy_override": "none"},
        "metadata": {"source": "hebrew_first_class", "category": "ephemeral"},
    },
    {
        "query": "מה מצב התנועה בכביש 6?",
        "labels": {"intent_family": "ephemeral", "evidence_mode": "not_required", "route": "EPHEMERAL", "policy_override": "none"},
        "metadata": {"source": "hebrew_first_class", "category": "ephemeral"},
    },
]


def load_existing_queries() -> set[str]:
    if not EXAMPLES_PATH.exists():
        return set()
    data = json.loads(EXAMPLES_PATH.read_text(encoding="utf-8"))
    return {item["query"].strip().lower() for item in data if "query" in item}


def backup_files() -> None:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    for src in (EXAMPLES_PATH, EMBEDDINGS_PATH, INDEX_PATH):
        if src.exists():
            dst = BACKUP_DIR / f"{src.stem}_{timestamp}{src.suffix}"
            shutil.copy2(src, dst)


def apply_changes(dry_run: bool = False) -> None:
    existing = load_existing_queries()
    additions = [ex for ex in NEW_EXAMPLES if ex["query"].strip().lower() not in existing]
    duplicates = len(NEW_EXAMPLES) - len(additions)

    if not additions:
        print("No new Hebrew examples to add (all are duplicates).")
        return

    if dry_run:
        print(f"Would add {len(additions)} new Hebrew examples ({duplicates} duplicates skipped).")
        for ex in additions:
            print(f"  [{ex['labels']['route']}] {ex['query']}")
        return

    backup_files()

    if EXAMPLES_PATH.exists():
        examples = json.loads(EXAMPLES_PATH.read_text(encoding="utf-8"))
    else:
        examples = []
    examples.extend(additions)
    EXAMPLES_PATH.write_text(json.dumps(examples, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Added {len(additions)} Hebrew examples ({duplicates} duplicates skipped).")
    route_counts = Counter(ex["labels"]["route"] for ex in additions)
    for route, count in sorted(route_counts.items()):
        print(f"  {route}: {count}")

    # Rebuild embeddings using the shared script.
    rebuild_script = ROUTER_DIR.parent.parent / "scripts" / "rebuild_embeddings.py"
    if rebuild_script.exists():
        print("Rebuilding embeddings...")
        sys.path.insert(0, str(rebuild_script.parent))
        import runpy

        runpy.run_path(str(rebuild_script), run_name="__main__")
    else:
        print(f"Warning: rebuild script not found at {rebuild_script}; embeddings not updated.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Append Hebrew router training examples")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without applying")
    args = parser.parse_args()
    apply_changes(dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
