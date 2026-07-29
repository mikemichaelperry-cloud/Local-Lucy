#!/usr/bin/env python3
"""Frozen router/governor baseline.

Behavior in this module is frozen except for demonstrated defect fixes.
New heuristics require targeted test coverage first.
Authority boundaries must not be weakened, and semantic-interpreter routing
authority must not be expanded casually.

This module is now a thin facade: plan construction, policy resolution,
contract building, and CLI wrapper live in ``router_py.planner`` submodules.
"""

import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
TOOLS_DIR = THIS_DIR.parent.parent / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from router_py.planner.cli import run_cli

main = run_cli

if __name__ == "__main__":
    sys.exit(run_cli())
