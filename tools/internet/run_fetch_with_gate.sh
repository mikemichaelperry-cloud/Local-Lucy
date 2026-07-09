#!/usr/bin/env bash
# Thin compatibility wrapper around the pure-Python fetch gate.
# The implementation has moved to fetch_gate.py; this script preserves the
# original CLI contract for existing shell callers.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$SCRIPT_DIR/fetch_gate.py" "$@"
