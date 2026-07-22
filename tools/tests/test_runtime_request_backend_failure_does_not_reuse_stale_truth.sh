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
if [[ "${q}" == "good" ]]; then
  cat > "${LUCY_ROOT}/state/last_route.env" <<EOF
UTC=2026-03-23T22:10:00Z
MODE=EVIDENCE
ROUTE_REASON=mock_route
SESSION_ID=req-session
QUERY=${q}
EOF
  cat > "${LUCY_ROOT}/state/last_outcome.env" <<EOF
UTC=2026-03-23T22:10:01Z
MODE=EVIDENCE
ROUTE_REASON=mock_route
SESSION_ID=req-session
EVIDENCE_CREATED=true
OUTCOME_CODE=answered
ACTION_HINT=
RC=0
QUERY=${q}
REQUESTED_MODE=EVIDENCE
FINAL_MODE=EVIDENCE
FALLBACK_USED=false
FALLBACK_REASON=none
TRUST_CLASS=evidence_backed
EOF
  printf 'BEGIN_VALIDATED\ngood payload\nEND_VALIDATED\n'
  exit 0
fi
printf 'backend exploded\n' >&2
exit 7
SH
chmod +x "${MOCK_ROOT}/lucy_chat.sh"

python3 "${CONTROL_TOOL}" --state-file "${STATE_FILE}" ensure-state >/dev/null

LUCY_RUNTIME_AUTHORITY_ROOT="${MOCK_ROOT}" \
LUCY_RUNTIME_REQUEST_MOCK=1 \
LUCY_RUNTIME_STATE_FILE="${STATE_FILE}" \
LUCY_RUNTIME_REQUEST_RESULT_FILE="${RESULT_FILE}" \
LUCY_RUNTIME_REQUEST_HISTORY_FILE="${HISTORY_FILE}" \
python3 "${REQUEST_TOOL}" submit --text "good" >/dev/null

[[ -f "${MOCK_ROOT}/state/last_route.env" ]] || die "good request should publish last_route.env"
[[ -f "${MOCK_ROOT}/state/last_outcome.env" ]] || die "good request should publish last_outcome.env"

if LUCY_RUNTIME_AUTHORITY_ROOT="${MOCK_ROOT}" \
  LUCY_RUNTIME_REQUEST_MOCK=1 \
  LUCY_RUNTIME_STATE_FILE="${STATE_FILE}" \
  LUCY_RUNTIME_REQUEST_RESULT_FILE="${RESULT_FILE}" \
  LUCY_RUNTIME_REQUEST_HISTORY_FILE="${HISTORY_FILE}" \
  python3 "${REQUEST_TOOL}" submit --text "bad" >/dev/null; then
  die "backend failure should return non-zero"
fi

python3 - <<'PY' "${RESULT_FILE}" "${MOCK_ROOT}/state/last_route.env" "${MOCK_ROOT}/state/last_outcome.env"
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
route_path = Path(sys.argv[2])
outcome_path = Path(sys.argv[3])

assert payload["status"] == "failed"
assert payload["accepted"] is True
assert payload["error"] == "backend exploded"
assert payload["route"]["mode"] == ""
assert payload["route"]["query"] == ""
assert payload["outcome"]["outcome_code"] == "execution_error"
assert payload["outcome"]["requested_mode"] == "unknown"
assert payload["outcome"]["final_mode"] == "ERROR"
assert payload["outcome"]["trust_class"] == "unknown"
assert payload["outcome"]["fallback_used"] == "false"
assert payload["outcome"]["fallback_reason"] == ""
assert payload["outcome"]["rc"] == 7

# Stale files from the previous successful request must not survive the crash.
assert not route_path.exists(), "stale last_route.env should be deleted after backend crash"
outcome_env = outcome_path.read_text(encoding="utf-8")
assert "OUTCOME_CODE=execution_error" in outcome_env
assert "FINAL_MODE=ERROR" in outcome_env
assert "FALLBACK_USED=false" in outcome_env
assert "FALLBACK_REASON=" in outcome_env
PY

ok "runtime_request clears stale truth metadata when backend fails before state refresh"
echo "PASS: test_runtime_request_backend_failure_does_not_reuse_stale_truth"
