#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DEFAULT="$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)"
ROOT="${LUCY_ROOT:-$ROOT_DEFAULT}"
MEM_FILE="${ROOT}/memory/memory.txt"
AUDIT_LOG="${ROOT}/audit/audit.log"

usage() {
  cat <<USAGE
Usage:
  Paste a [MEMORY PROPOSAL] block into stdin, then:
    ./tools/lucy-mem-commit.sh

Example:
  cat <<'P' | ./tools/lucy-mem-commit.sh
  [MEMORY PROPOSAL]
  type: entity
  subject: Oscar
  summary: Oscar is Mike’s dog; fixation on cats; training uses leave-it, distance, reward.
  confidence: high
  P
USAGE
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

mkdir -p "$(dirname "$MEM_FILE")" "$(dirname "$AUDIT_LOG")"

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

# Read stdin (must not be empty)
cat > "$TMP"
if [[ ! -s "$TMP" ]]; then
  echo "ERROR: No input received on stdin." >&2
  usage >&2
  exit 1
fi

# Normalize CRLF
sed -i 's/\r$//' "$TMP"

# Extract required fields from proposal
if ! grep -q '^\[MEMORY PROPOSAL\]' "$TMP"; then
  echo "ERROR: Input must include a line exactly: [MEMORY PROPOSAL]" >&2
  exit 1
fi

TYPE="$(awk -F': *' 'tolower($1)=="type"{print $2; exit}' "$TMP" | tr -d '\r')"
SUBJECT="$(awk -F': *' 'tolower($1)=="subject"{print $2; exit}' "$TMP" | tr -d '\r')"
SUMMARY="$(awk -F': *' 'tolower($1)=="summary"{print $2; exit}' "$TMP" | tr -d '\r')"

if [[ -z "${TYPE}" || -z "${SUBJECT}" || -z "${SUMMARY}" ]]; then
  echo "ERROR: Proposal must contain non-empty lines for: type:, subject:, summary:" >&2
  echo "Found: type='${TYPE:-}' subject='${SUBJECT:-}' summary='${SUMMARY:-}'" >&2
  exit 1
fi

# ID + timestamps
APPROVED_AT="$(date -Is)"
RAND="$(printf "%05d" $((RANDOM % 100000)))"
ID="$(date +%Y%m%d-%H%M%S)-${RAND}"

# Append to memory.txt (append-only)
{
  echo
  echo "----"
  echo "[MEMORY ITEM] id=${ID} approved_at=${APPROVED_AT}"
  echo "type: ${TYPE}"
  echo "subject: ${SUBJECT}"
  echo
  echo "${SUMMARY}"
  echo
  echo "[PROVENANCE]"
  echo "committed_by: human"
  echo "source: stdin proposal"
  echo "---- BEGIN PROPOSAL ----"
  cat "$TMP"
  echo "---- END PROPOSAL ----"
} >> "$MEM_FILE"

# Audit
echo "${APPROVED_AT} | COMMIT | id=${ID} type=${TYPE} subject=${SUBJECT} mem_file=${MEM_FILE}" >> "$AUDIT_LOG"

echo "Committed memory item:"
echo "  id:      ${ID}"
echo "  type:    ${TYPE}"
echo "  subject: ${SUBJECT}"
echo "  file:    ${MEM_FILE}"
