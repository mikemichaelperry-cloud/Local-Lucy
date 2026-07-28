#!/usr/bin/env python3
"""Local Lucy deterministic policy-router package."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure tools package is importable when this module is loaded directly.
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

if str(ROOT_DIR / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "tools"))

from router_py.policy import requires_evidence_mode

from .models import PolicyDecision
from .router import PolicyRouter

__all__ = ["PolicyDecision", "PolicyRouter", "requires_evidence_mode"]
