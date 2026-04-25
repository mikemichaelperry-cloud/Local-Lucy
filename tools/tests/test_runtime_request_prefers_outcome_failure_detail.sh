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
UTC=2026-03-24T17:20:00Z
MODE=LOCAL
ROUTE_REASON=mock_route
SESSION_ID=
QUERY=${q}
EOF
cat > "${LUCY_ROOT}/state/last_outcome.env" <<EOF
UTC=2026-03-24T17:20:01Z
MODE=AUGMENTED
ROUTE_REASON=mock_route
SESSION_ID=
EVIDENCE_CREATED=false
OUTCOME_CODE=execution_error
ACTION_HINT=Grok provider is selected but missing configuration.
RC=7
QUERY=${q}
REQUESTED_MODE=AUGMENTED
FINAL_MODE=AUGMENTED
FALLBACK_USED=false
FALLBACK_REASON=direct_grok_provider_unavailable
TRUST_CLASS=unverified
AUGMENTED_PROVIDER=grok
EOF
printf 'generic backend stderr\n' >&2
exit 7
SH
chmod +x "${MOCK_ROOT}/lucy_chat.sh"

python3 "${CONTROL_TOOL}" --state-file "${STATE_FILE}" ensure-state >/dev/null

if LUCY_RUNTIME_AUTHORITY_ROOT="${MOCK_ROOT}" \
  LUCY_RUNTIME_STATE_FILE="${STATE_FILE}" \
  LUCY_RUNTIME_REQUEST_RESULT_FILE="${RESULT_FILE}" \
  LUCY_RUNTIME_REQUEST_HISTORY_FILE="${HISTORY_FILE}" \
  python3 "${REQUEST_TOOL}" submit --text "grok detail check" >/dev/null; then
  die "request should fail"
fi

python3 - <<'PY' "${RESULT_FILE}"
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert payload["status"] == "failed"
assert payload["error"] == "Grok provider is selected but missing configuration."
assert payload["outcome"]["outcome_code"] == "execution_error"
assert payload["outcome"]["augmented_provider"] == "grok"
assert payload["outcome"]["fallback_reason"] == "direct_grok_provider_unavailable"
assert payload["outcome"]["rc"] == 7
PY

ok "runtime_request prefers provider-specific outcome failure detail when valid outcome metadata exists"
echo "PASS: test_runtime_request_prefers_outcome_failure_detail"
