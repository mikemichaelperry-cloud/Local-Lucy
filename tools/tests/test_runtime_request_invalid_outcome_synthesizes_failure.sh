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
UTC=2026-03-23T22:20:00Z
MODE=EVIDENCE
ROUTE_REASON=mock_invalid_outcome
SESSION_ID=invalid-session
QUERY=${q}
EOF
: > "${LUCY_ROOT}/state/last_outcome.env"
printf 'BEGIN_VALIDATED\npartial reply\nEND_VALIDATED\n'
SH
chmod +x "${MOCK_ROOT}/lucy_chat.sh"

python3 "${CONTROL_TOOL}" --state-file "${STATE_FILE}" ensure-state >/dev/null

if LUCY_RUNTIME_AUTHORITY_ROOT="${MOCK_ROOT}" \
  LUCY_RUNTIME_STATE_FILE="${STATE_FILE}" \
  LUCY_RUNTIME_REQUEST_RESULT_FILE="${RESULT_FILE}" \
  LUCY_RUNTIME_REQUEST_HISTORY_FILE="${HISTORY_FILE}" \
  python3 "${REQUEST_TOOL}" submit --text "invalid outcome case" >/dev/null; then
  die "invalid outcome publication should fail"
fi

python3 - <<'PY' "${RESULT_FILE}" "${MOCK_ROOT}/state/last_outcome.env"
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
outcome_env = Path(sys.argv[2]).read_text(encoding="utf-8")

assert payload["status"] == "failed"
assert payload["error"] == "backend did not publish valid outcome state"
assert payload["outcome"]["outcome_code"] == "execution_error"
assert payload["outcome"]["final_mode"] == "ERROR"
assert payload["outcome"]["fallback_used"] == "false"
assert payload["outcome"]["trust_class"] == "unknown"
assert payload["route"]["mode"] == "EVIDENCE"

assert "OUTCOME_CODE=execution_error" in outcome_env
assert "FINAL_MODE=ERROR" in outcome_env
assert "TRUST_CLASS=unknown" in outcome_env
assert "FALLBACK_USED=false" in outcome_env
PY

ok "runtime_request synthesizes explicit failure truth when outcome file is empty or invalid"
echo "PASS: test_runtime_request_invalid_outcome_synthesizes_failure"
