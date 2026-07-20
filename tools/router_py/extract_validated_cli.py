#!/usr/bin/env python3
import json
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
TOOLS_DIR = THIS_DIR.parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from router_py.core.extract_validated import parse


def main():
    text = sys.stdin.read()
    print(json.dumps(parse(text), separators=(",", ":"), sort_keys=True))


if __name__ == "__main__":
    main()
