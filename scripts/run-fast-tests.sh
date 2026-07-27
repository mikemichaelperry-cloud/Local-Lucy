#!/usr/bin/env bash
# Run the fast default test suite (excludes slow/live tests).
# To run the full suite including slow/live tests:
#   python3 -m pytest tools/router_py/ -m ""
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m pytest tools/router_py/ -q --tb=line "$@"
