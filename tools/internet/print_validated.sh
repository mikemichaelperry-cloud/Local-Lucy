#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DEFAULT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"
ROOT="${LUCY_ROOT:-$ROOT_DEFAULT}"
VALIDATOR="${ROOT}/tools/internet/validate_answer.py"
EVIDENCE_ROOT="${LUCY_EVIDENCE_ROOT:-${ROOT}/evidence}"

FORCE=0
if [[ "${1:-}" == "--force" ]]; then
  FORCE=1
  shift
fi

MODE="${1:-single}"

TXT="$(cat)"

# Enforce validation if forced OR if evidence mode is enabled in env.
if [[ "$FORCE" -ne 1 && "${EVIDENCE_MODE:-0}" != "1" ]]; then
  printf '%s' "$TXT"
  exit 0
fi

if printf '%s' "$TXT" | "$VALIDATOR" --mode "$MODE" --evidence-root "$EVIDENCE_ROOT" >/dev/null 2>&1; then
  printf '%s' "$TXT"
else
  printf '%s\n' "Insufficient evidence from trusted sources."
  exit 3
fi
