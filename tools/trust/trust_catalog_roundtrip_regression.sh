#!/usr/bin/env bash
set -euo pipefail
ROOT="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
GEN="$ROOT/tools/trust/generate_trust_lists.py"
VER="$ROOT/tools/trust/verify_trust_lists.sh"
TMP1="$(mktemp)"
TMP2="$(mktemp)"
trap 'rm -f "$TMP1" "$TMP2"' EXIT
[[ -x "$GEN" ]] || { echo "ERR: missing generator" >&2; exit 1; }
[[ -x "$VER" ]] || { echo "ERR: missing verifier" >&2; exit 1; }
python3 "$GEN" >/dev/null
find "$ROOT/config/trust/generated" -type f | sort | xargs sha256sum > "$TMP1"
python3 "$GEN" >/dev/null
find "$ROOT/config/trust/generated" -type f | sort | xargs sha256sum > "$TMP2"
diff -u "$TMP1" "$TMP2" >/dev/null
"$VER" >/dev/null
echo "PASS: trust_catalog_roundtrip_regression"
