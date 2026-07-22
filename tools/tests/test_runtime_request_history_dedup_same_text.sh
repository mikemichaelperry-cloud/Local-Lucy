#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"
REQUEST_TOOL="${ROOT}/tools/runtime_request.py"
CONTROL_TOOL="${ROOT}/tools/runtime_control.py"

ok(){ echo "OK: $*"; }
die(){ echo "FAIL: $*" >&2; exit 1; }

[[ -f "${REQUEST_TOOL}" ]] || die "missing request tool: ${REQUEST_TOOL}"
[[ -f "${CONTROL_TOOL}" ]] || die "missing control tool: ${CONTROL_TOOL}"

TMPD="$(mktemp -d)"
export LUCY_RUNTIME_NAMESPACE_ROOT="${TMPD}"
trap 'rm -rf "${TMPD}"' EXIT
STATE_FILE="${TMPD}/current_state.json"
RESULT_FILE="${TMPD}/last_request_result.json"
HISTORY_FILE="${TMPD}/request_history.jsonl"
MOCK_ROOT="${TMPD}/mock_root"
mkdir -p "${MOCK_ROOT}/state"

cat > "${MOCK_ROOT}/lucy_chat.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
q="${1:-}"
mkdir -p "${LUCY_ROOT}/state"
cat > "${LUCY_ROOT}/state/last_route.env" <<EOF
UTC=2026-07-22T19:00:00Z
MODE=LOCAL
ROUTE_REASON=mock_route
SESSION_ID=
QUERY=${q}
EOF
cat > "${LUCY_ROOT}/state/last_outcome.env" <<EOF
UTC=2026-07-22T19:00:01Z
MODE=LOCAL
ROUTE_REASON=mock_route
SESSION_ID=
EVIDENCE_CREATED=false
OUTCOME_CODE=answered
ACTION_HINT=
RC=0
QUERY=${q}
REQUESTED_MODE=LOCAL
FINAL_MODE=LOCAL
FALLBACK_USED=false
FALLBACK_REASON=none
TRUST_CLASS=
EOF
printf 'BEGIN_VALIDATED\nmock reply: %s\nEND_VALIDATED\n' "${q}"
SH
chmod +x "${MOCK_ROOT}/lucy_chat.sh"

python3 "${CONTROL_TOOL}" --state-file "${STATE_FILE}" ensure-state >/dev/null

run_submit() {
  local prompt="$1"
  LUCY_RUNTIME_AUTHORITY_ROOT="${MOCK_ROOT}" \
  LUCY_RUNTIME_REQUEST_MOCK=1 \
  LUCY_RUNTIME_STATE_FILE="${STATE_FILE}" \
  LUCY_RUNTIME_REQUEST_RESULT_FILE="${RESULT_FILE}" \
  LUCY_RUNTIME_REQUEST_HISTORY_FILE="${HISTORY_FILE}" \
  python3 "${REQUEST_TOOL}" submit --text "${prompt}"
}

first="$(run_submit "repeat me")"
second="$(run_submit "repeat me")"

python3 - "${first}" "${second}" "${HISTORY_FILE}" <<'PY'
import json
import sys
from pathlib import Path

first = json.loads(sys.argv[1])
second = json.loads(sys.argv[2])
history_lines = Path(sys.argv[3]).read_text(encoding="utf-8").splitlines()
entries = [json.loads(line) for line in history_lines]

assert first["status"] == "completed"
assert second["status"] == "completed"
assert first["request_text"] == "repeat me"
assert second["request_text"] == "repeat me"
assert first["response_text"] == "mock reply: repeat me"
assert second["response_text"] == "mock reply: repeat me"

# Each submit is a distinct execution and must produce its own history entry.
assert len(entries) == 2, f"expected 2 history entries, got {len(entries)}"
assert entries[0]["request_id"] != entries[1]["request_id"]
assert entries[0]["request_text"] == entries[1]["request_text"] == "repeat me"
assert entries[0]["response_text"] == entries[1]["response_text"] == "mock reply: repeat me"
PY

ok "runtime_request writes two distinct history entries for the same submitted text"
echo "PASS: test_runtime_request_history_dedup_same_text"
