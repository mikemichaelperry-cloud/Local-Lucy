#!/usr/bin/env bash
# ROLE: PRIMARY AUTHORITATIVE ENTRYPOINT
# Resume helper for the active Local Lucy handoff flow.
# Preferred handoff resume surface for new workflows.
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${LUCY_ROOT:-$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)}"
DEV_NOTES_DIR="${ROOT}/dev_notes"
LATEST_HANDOFF_POINTER="${DEV_NOTES_DIR}/LATEST_SESSION_HANDOFF.txt"

usage() {
  cat <<'USAGE'
Usage:
  resume_local_lucy_from_handoff.sh [--open] [--path-only]

Finds the newest SESSION_HANDOFF note for the active snapshot and prints a short
resume block plus the exact "First commands to run next" section.

Options:
  --open       Print the full handoff after the resume block
  --path-only  Print only the newest handoff path
  -h, --help   Show this help
USAGE
}

PRINT_FILE=0
PATH_ONLY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --open)
      PRINT_FILE=1
      ;;
    --path-only)
      PATH_ONLY=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "ERR: unknown arg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift || true
done

latest_handoff=""
if [[ -f "${LATEST_HANDOFF_POINTER}" ]]; then
  latest_handoff="$(head -n1 "${LATEST_HANDOFF_POINTER}" | tr -d '\r' | sed 's/[[:space:]]*$//')"
fi
if [[ -z "${latest_handoff}" || ! -f "${latest_handoff}" ]]; then
  latest_handoff="$(
    ls -1 "${DEV_NOTES_DIR}"/SESSION_HANDOFF_*.md 2>/dev/null | sort | tail -1 || true
  )"
fi

if [[ -z "${latest_handoff}" ]]; then
  echo "ERR: no SESSION_HANDOFF files found under ${DEV_NOTES_DIR}" >&2
  exit 1
fi

if [[ "${PATH_ONLY}" == "1" ]]; then
  printf '%s\n' "${latest_handoff}"
  exit 0
fi

extract_section() {
  local header="$1"
  python3 - "$latest_handoff" "$header" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
header = sys.argv[2]
lines = path.read_text(encoding="utf-8").splitlines()

in_section = False
for line in lines:
    if line.startswith("## "):
        if in_section:
            break
        in_section = (line.strip() == header)
        continue
    if in_section:
        print(line)
PY
}

quick_resume="$(extract_section '## Quick Resume')"
session_changes="$(extract_section '## Session Changes')"

echo "Newest handoff:"
echo "  ${latest_handoff}"
echo
echo "Quick resume:"
printf '%s\n' "${quick_resume}" | sed 's/^/  /'
echo
echo "Session changes:"
printf '%s\n' "${session_changes}" | sed 's/^/  /'
echo
echo "Suggested start:"
printf '%s\n' "${quick_resume}" | awk '
  /- \*\*First commands to run next\*\*:/ {capture=1; next}
  capture && /^- \*\*/ {exit}
  capture && /^## / {exit}
  capture {print}
' | sed 's/^/  /'

if [[ "${PRINT_FILE}" == "1" ]]; then
  echo
  echo "---"
  echo
  cat "${latest_handoff}"
fi
