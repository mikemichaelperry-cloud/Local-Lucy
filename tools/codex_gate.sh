#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
else
  echo "ERROR: codex_gate.sh requires python3 or python on PATH." >&2
  exit 1
fi

set +e
output="$("${PYTHON_BIN}" "${SCRIPT_DIR}/codex_gate.py" "$@")"
rc=$?
set -e
printf '%s\n' "$output"
if [ "$rc" -ne 0 ]; then
  exit "$rc"
fi

declare -A gate_values=()
while IFS= read -r line; do
  [ -n "$line" ] || continue
  key="${line%%=*}"
  value="${line#*=}"
  gate_values["$key"]="$value"
done <<< "$output"

export LUCY_DECISION="${gate_values[DECISION]:-}"
export LUCY_CLEANED_TASK="${gate_values[CLEANED_TASK]:-}"
export LUCY_SCOPE_TARGETS="${gate_values[TARGET_FILES]:-}"
export LUCY_SCOPE_ALLOWED="${gate_values[ALLOWED_PATHS]:-}"
export LUCY_SCOPE_EXCLUDED="${gate_values[EXCLUDED_PATHS]:-}"
export LUCY_PATCH_SURFACE="${gate_values[PATCH_SURFACE]:-}"
export LUCY_VALIDATION_PLAN="${gate_values[VALIDATION_PLAN]:-}"
export LUCY_CONSTRAINTS="${gate_values[CONSTRAINTS]:-}"
export LUCY_SANITY_FLAGS="${gate_values[SANITY_FLAGS]:-}"
export LUCY_MODEL_HINT="${gate_values[MODEL_HINT]:-}"
export LUCY_EFFORT_HINT="${gate_values[EFFORT_HINT]:-}"
exit 0
