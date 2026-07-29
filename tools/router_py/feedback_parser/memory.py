#!/usr/bin/env python3
"""Memory retraction helpers for feedback processing."""

from __future__ import annotations

import os
from pathlib import Path


def _retract_from_memory(query: str) -> None:
    """Remove a query from session memory if present."""
    try:
        mem_file = os.environ.get("LUCY_CHAT_MEMORY_FILE", "").strip()
        if not mem_file:
            return
        mem_path = Path(mem_file).expanduser()
        if not mem_path.exists():
            return
        content = mem_path.read_text(encoding="utf-8")
        blocks = [b.strip() for b in content.split("\n\n") if b.strip()]
        filtered = []
        for block in blocks:
            # Simple heuristic: if the block starts with this query, skip it
            if not block.lower().startswith(f"user: {query.lower()}"):
                filtered.append(block)
        if len(filtered) != len(blocks):
            mem_path.write_text("\n\n".join(filtered) + "\n\n", encoding="utf-8")
    except Exception:
        pass
