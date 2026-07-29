#!/usr/bin/env python3
"""Background-learning trigger for feedback processing."""

from __future__ import annotations

import sys
from pathlib import Path


def trigger_background_learning() -> bool:
    """Trigger background learner to rebuild embeddings from new feedback.

    Returns True if learning was triggered.
    """
    try:
        router_dir = str(Path(__file__).resolve().parent.parent.parent.parent / "models" / "router")
        inserted = False
        if router_dir not in sys.path:
            sys.path.insert(0, router_dir)
            inserted = True

        from background_learner import maybe_auto_learn

        triggered = maybe_auto_learn(min_entries=1)

        if inserted and router_dir in sys.path:
            sys.path.remove(router_dir)

        return triggered
    except Exception as e:
        print(f"[Background learning trigger failed] {e}")
        return False
