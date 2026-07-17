#!/usr/bin/env python3
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
TOOLS_DIR = THIS_DIR.parent.parent / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from router_py.core.medical_fact_extractor import main

if __name__ == "__main__":
    raise SystemExit(main())
