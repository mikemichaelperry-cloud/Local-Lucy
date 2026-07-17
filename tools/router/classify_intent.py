#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
# Import canonical router core from router_py (single source of truth)
TOOLS_DIR = THIS_DIR.parent.parent / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from router_py.core.intent_classifier import classify_question


def main() -> int:
    if len(sys.argv) > 1:
        question = " ".join(sys.argv[1:])
    else:
        question = sys.stdin.read()
    surface = (os.environ.get("LUCY_SURFACE") or "cli").strip().lower() or "cli"
    output = classify_question(question, surface=surface)
    print(json.dumps(output, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
