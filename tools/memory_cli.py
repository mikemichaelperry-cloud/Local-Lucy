#!/usr/bin/env python3
"""Simple CLI for managing persistent facts in Lucy's SQLite memory.db.

Usage:
    python tools/memory_cli.py list
    python tools/memory_cli.py add "Netta is Rachel's daughter." --category family
    python tools/memory_cli.py delete <id>
    python tools/memory_cli.py import-memory-txt
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running from repo root
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from memory.memory_service import (
    _get_connection,
    delete_persistent_fact,
    get_persistent_facts,
    store_persistent_fact,
)


def cmd_list(args: argparse.Namespace) -> int:
    facts = get_persistent_facts(args.category)
    if not facts:
        print("No persistent facts found.")
        return 0
    for i, text in enumerate(facts, 1):
        print(f"  {i}. {text}")
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    sid = store_persistent_fact(args.text, args.category)
    print(f"Stored fact id={sid}: {args.text[:60]}{'...' if len(args.text) > 60 else ''}")
    return 0


def cmd_delete(args: argparse.Namespace) -> int:
    delete_persistent_fact(args.id)
    print(f"Deleted fact id={args.id}.")
    return 0


def cmd_import_memory_txt(args: argparse.Namespace) -> int:
    """Import legacy memory/memory.txt into persistent_facts."""
    mem_path = ROOT / "memory" / "memory.txt"
    if not mem_path.exists():
        print(f"memory.txt not found at {mem_path}")
        return 1

    text = mem_path.read_text(encoding="utf-8")
    lines = [l.strip() for l in text.splitlines() if l.strip() and not l.startswith("-")]
    imported = 0
    for line in lines:
        # Skip header lines and old metadata blocks
        if line.startswith("[") or line.startswith("----"):
            continue
        if len(line) < 10:
            continue
        store_persistent_fact(line, category="imported")
        imported += 1
    print(f"Imported {imported} facts from {mem_path}")
    return 0


def cmd_reset(args: argparse.Namespace) -> int:
    """Delete all persistent_facts (use with caution)."""
    conn = _get_connection()
    cur = conn.execute("SELECT COUNT(*) FROM persistent_facts")
    count = cur.fetchone()[0]
    conn.execute("DELETE FROM persistent_facts")
    conn.commit()
    print(f"Deleted {count} persistent facts.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage Lucy's persistent facts")
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="List all persistent facts")
    p_list.add_argument("--category", default=None, help="Filter by category")

    p_add = sub.add_parser("add", help="Add a persistent fact")
    p_add.add_argument("text", help="Fact text")
    p_add.add_argument("--category", default=None, help="Category tag")

    p_del = sub.add_parser("delete", help="Delete a fact by id")
    p_del.add_argument("id", type=int, help="Fact id")

    sub.add_parser("import-memory-txt", help="Import legacy memory/memory.txt")
    sub.add_parser("reset", help="Delete ALL persistent facts")

    args = parser.parse_args()
    handlers = {
        "list": cmd_list,
        "add": cmd_add,
        "delete": cmd_delete,
        "import-memory-txt": cmd_import_memory_txt,
        "reset": cmd_reset,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
