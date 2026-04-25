#!/usr/bin/env python3
import sys
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
CORE_DIR = THIS_DIR / "core"
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

from medical_fact_extractor import main


if __name__ == "__main__":
    raise SystemExit(main())
