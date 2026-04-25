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
UI_STATE_DIR="${TMPD}/ui_state"
MOCK_ROOT="${TMPD}/mock_root"

mkdir -p "${MOCK_ROOT}/state" "${MOCK_ROOT}/config" "${MOCK_ROOT}/tools" "${UI_STATE_DIR}"
printf 'demo_key_1\n' > "${MOCK_ROOT}/config/evidence_keys_allowlist.txt"

cat > "${MOCK_ROOT}/lucy_chat.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
mkdir -p "${LUCY_ROOT}/state"
q="${1:-}"
query_sha256(){ printf '%s' "$1" | sha256sum | awk '{print $1}'; }
echo "${LUCY_AUGMENTED_PROVIDER:-unset}" > "${LUCY_ROOT}/state/seen_augmented_provider.txt"
if [[ "${q}" == "fail case" ]]; then
  {
    echo "UTC=2026-03-20T18:00:00Z"
    echo "MODE=LOCAL"
    echo "ROUTE_REASON=mock_failure"
    echo "SESSION_ID="
    echo "QUERY=${q}"
    echo "QUERY_SHA256=$(query_sha256 "${q}")"
  } > "${LUCY_ROOT}/state/last_route.env"
  {
    echo "UTC=2026-03-20T18:00:01Z"
    echo "MODE=LOCAL"
    echo "ROUTE_REASON=mock_failure"
    echo "SESSION_ID="
    echo "EVIDENCE_CREATED=false"
    echo "OUTCOME_CODE=execution_error"
    echo "ACTION_HINT=check mock backend"
    echo "RC=7"
    echo "QUERY=${q}"
    echo "QUERY_SHA256=$(query_sha256 "${q}")"
  } > "${LUCY_ROOT}/state/last_outcome.env"
  echo "mock backend failed" >&2
  exit 7
fi
{
  echo "UTC=2026-03-20T18:00:00Z"
  echo "MODE=LOCAL"
  echo "ROUTE_REASON=mock_route"
  echo "SESSION_ID="
  echo "QUERY=${q}"
  echo "QUERY_SHA256=$(query_sha256 "${q}")"
} > "${LUCY_ROOT}/state/last_route.env"
{
  echo "UTC=2026-03-20T18:00:01Z"
  echo "MODE=LOCAL"
  echo "ROUTE_REASON=mock_route"
  echo "SESSION_ID="
  echo "EVIDENCE_CREATED=false"
  echo "OUTCOME_CODE=answered"
  echo "ACTION_HINT="
  echo "RC=0"
  echo "QUERY=${q}"
  echo "QUERY_SHA256=$(query_sha256 "${q}")"
} > "${LUCY_ROOT}/state/last_outcome.env"
printf 'BEGIN_VALIDATED\nmock reply: %s\nEND_VALIDATED\n' "${q}"
SH
chmod +x "${MOCK_ROOT}/lucy_chat.sh"

python3 "${CONTROL_TOOL}" --state-file "${STATE_FILE}" ensure-state >/dev/null
python3 "${CONTROL_TOOL}" --state-file "${STATE_FILE}" set-augmented-provider --value openai >/dev/null

success_json="$(
  LUCY_RUNTIME_AUTHORITY_ROOT="${MOCK_ROOT}" \
  LUCY_RUNTIME_STATE_FILE="${STATE_FILE}" \
  LUCY_RUNTIME_REQUEST_RESULT_FILE="${RESULT_FILE}" \
  LUCY_RUNTIME_REQUEST_HISTORY_FILE="${HISTORY_FILE}" \
  LUCY_UI_STATE_DIR="${UI_STATE_DIR}" \
  python3 "${REQUEST_TOOL}" submit --text "hello mock"
)"

python3 - <<'PY' "${success_json}" "${RESULT_FILE}" "${HISTORY_FILE}" "${UI_STATE_DIR}/last_route.json"
import json
import sys
from pathlib import Path

payload = json.loads(sys.argv[1])
persisted = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
history_lines = Path(sys.argv[3]).read_text(encoding="utf-8").splitlines()
history_entry = json.loads(history_lines[0])
route_snapshot = json.loads(Path(sys.argv[4]).read_text(encoding="utf-8"))
assert payload["status"] == "completed"
assert payload["accepted"] is True
assert payload["response_text"] == "mock reply: hello mock"
assert payload["route"]["mode"] == "LOCAL"
assert payload["outcome"]["outcome_code"] == "answered"
assert payload["outcome"]["answer_class"] == "local_answer"
assert payload["outcome"]["provider_authorization"] == "not_applicable"
assert payload["outcome"]["operator_trust_label"] == "local"
assert payload["outcome"]["operator_answer_path"] == "Local answer"
assert payload["control_state"]["augmentation_policy"] == "fallback_only"
assert payload["control_state"]["augmented_provider"] == "openai"
assert payload["outcome"]["requested_mode"] == ""
assert payload["outcome"]["final_mode"] == ""
assert payload["outcome"]["trust_class"] == ""
assert persisted == payload
assert len(history_lines) == 1
assert history_entry["request_id"] == payload["request_id"]
assert history_entry["status"] == "completed"
assert history_entry["request_text"] == "hello mock"
assert history_entry["response_text"] == "mock reply: hello mock"
assert history_entry["control_state"]["augmentation_policy"] == "fallback_only"
assert history_entry["control_state"]["augmented_provider"] == "openai"
assert route_snapshot["route"] == "LOCAL"
assert route_snapshot["current_route"] == "LOCAL"
assert route_snapshot["source_type"] == "local"
assert route_snapshot["answer_class"] == "local_answer"
assert route_snapshot["operator_trust_label"] == "local"
assert route_snapshot["provider_authorization"] == "not_applicable"
assert route_snapshot["route_reason"] == "mock_route"
assert route_snapshot["provider_used"] == "none"
PY

multiline_json="$(
  LUCY_RUNTIME_AUTHORITY_ROOT="${MOCK_ROOT}" \
  LUCY_RUNTIME_STATE_FILE="${STATE_FILE}" \
  LUCY_RUNTIME_REQUEST_RESULT_FILE="${RESULT_FILE}" \
  LUCY_RUNTIME_REQUEST_HISTORY_FILE="${HISTORY_FILE}" \
  LUCY_UI_STATE_DIR="${UI_STATE_DIR}" \
  python3 "${REQUEST_TOOL}" submit --text $'hello mock\nsecond line'
)"

python3 - <<'PY' "${multiline_json}" "${RESULT_FILE}" "${HISTORY_FILE}"
import json
import sys
from pathlib import Path

payload = json.loads(sys.argv[1])
persisted = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
history_lines = Path(sys.argv[3]).read_text(encoding="utf-8").splitlines()
history_entry = json.loads(history_lines[-1])
assert payload["status"] == "completed"
assert payload["accepted"] is True
assert payload["request_text"] == "hello mock\nsecond line"
assert payload["route"]["query"] == "hello mock\nsecond line"
assert payload["response_text"] == "mock reply: hello mock\nsecond line"
assert persisted == payload
assert history_entry["request_text"] == "hello mock\nsecond line"
assert history_entry["status"] == "completed"
PY

[[ "$(cat "${MOCK_ROOT}/state/seen_augmented_provider.txt")" == "openai" ]] || die "runtime_request did not pass selected augmented provider to execution env"

python3 - <<'PY' "${REQUEST_TOOL}" "${HISTORY_FILE}" "${RESULT_FILE}"
import json
import sys
from pathlib import Path

tool_path = Path(sys.argv[1])
history_path = Path(sys.argv[2])
payload = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
sys.path.insert(0, str(tool_path.parent))
import runtime_request as module
module.append_history_entry(history_path, payload)
history_lines = history_path.read_text(encoding="utf-8").splitlines()
assert len(history_lines) == 2
PY

python3 - <<'PY' "${REQUEST_TOOL}" "${TMPD}"
import json
import os
import re
import sys
from pathlib import Path

tool_path = Path(sys.argv[1])
tmp_root = Path(sys.argv[2])
history_dir = tmp_root / "rotation_case"
history_dir.mkdir(parents=True, exist_ok=True)
history_path = history_dir / "request_history.jsonl"

sys.path.insert(0, str(tool_path.parent))
import runtime_request as module

os.environ["LUCY_RUNTIME_REQUEST_HISTORY_MAX_ENTRIES"] = "2"

def payload(request_id: str) -> dict[str, object]:
    return {
        "completed_at": f"2026-03-20T18:00:0{request_id[-1]}Z",
        "error": "",
        "outcome": {
            "action_hint": "",
            "requested_mode": "",
            "final_mode": "",
            "fallback_used": "",
            "fallback_reason": "",
            "trust_class": "",
            "augmentation_policy": "",
            "augmented_direct_request": "",
            "evidence_created": "false",
            "outcome_code": "answered",
            "rc": 0,
            "utc": f"2026-03-20T18:00:0{request_id[-1]}Z",
        },
        "request_id": request_id,
        "request_text": f"request {request_id}",
        "response_text": f"response {request_id}",
        "route": {
            "mode": "LOCAL",
            "requested_mode": "",
            "final_mode": "",
            "query": f"request {request_id}",
            "reason": "rotation_test",
            "session_id": "",
            "utc": f"2026-03-20T18:00:0{request_id[-1]}Z",
        },
        "status": "completed",
    }

module.append_history_entry(history_path, payload("req-1"))
module.append_history_entry(history_path, payload("req-2"))
module.append_history_entry(history_path, payload("req-3"))

active_lines = history_path.read_text(encoding="utf-8").splitlines()
active_entries = [json.loads(line) for line in active_lines]
archive_paths = sorted(history_dir.glob("request_history.*.jsonl"))
assert [entry["request_id"] for entry in active_entries] == ["req-2", "req-3"]
assert len(archive_paths) == 1
assert re.match(r"request_history\.\d{8}-\d{6}(?:-\d+)?\.jsonl", archive_paths[0].name)
archive_entries = [json.loads(line) for line in archive_paths[0].read_text(encoding="utf-8").splitlines()]
assert [entry["request_id"] for entry in archive_entries] == ["req-1"]

module.append_history_entry(history_path, payload("req-1"))
active_lines = history_path.read_text(encoding="utf-8").splitlines()
archive_paths_after_duplicate = sorted(history_dir.glob("request_history.*.jsonl"))
assert len(active_lines) == 2
assert len(archive_paths_after_duplicate) == 1

module.append_history_entry(history_path, payload("req-4"))
active_entries = [json.loads(line) for line in history_path.read_text(encoding="utf-8").splitlines()]
archive_paths = sorted(history_dir.glob("request_history.*.jsonl"))
archived_request_ids = []
for archive_path in archive_paths:
    archived_request_ids.extend(
        json.loads(line)["request_id"]
        for line in archive_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )

assert [entry["request_id"] for entry in active_entries] == ["req-3", "req-4"]
assert sorted(archived_request_ids) == ["req-1", "req-2"]
PY

if LUCY_RUNTIME_AUTHORITY_ROOT="${MOCK_ROOT}" LUCY_RUNTIME_STATE_FILE="${STATE_FILE}" LUCY_RUNTIME_REQUEST_RESULT_FILE="${RESULT_FILE}" \
  LUCY_RUNTIME_REQUEST_HISTORY_FILE="${HISTORY_FILE}" LUCY_UI_STATE_DIR="${UI_STATE_DIR}" \
  python3 "${REQUEST_TOOL}" submit --text "   " >/tmp/runtime_request_empty.out 2>/tmp/runtime_request_empty.err; then
  die "empty submit should fail"
fi
python3 - <<'PY' "${RESULT_FILE}" "${HISTORY_FILE}"
import json
import sys
from pathlib import Path
payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
history_lines = Path(sys.argv[2]).read_text(encoding="utf-8").splitlines()
history_entry = json.loads(history_lines[-1])
assert payload["status"] == "rejected"
assert payload["accepted"] is False
assert payload["error"] == "empty submit text"
assert history_entry["status"] == "rejected"
assert history_entry["error"] == "empty submit text"
PY

if LUCY_RUNTIME_AUTHORITY_ROOT="${MOCK_ROOT}" LUCY_RUNTIME_STATE_FILE="${STATE_FILE}" LUCY_RUNTIME_REQUEST_RESULT_FILE="${RESULT_FILE}" \
  LUCY_RUNTIME_REQUEST_HISTORY_FILE="${HISTORY_FILE}" LUCY_UI_STATE_DIR="${UI_STATE_DIR}" \
  python3 "${REQUEST_TOOL}" submit --text "fail case" >/tmp/runtime_request_fail.out 2>/tmp/runtime_request_fail.err; then
  die "backend failure should return non-zero"
fi
python3 - <<'PY' "${RESULT_FILE}" "${HISTORY_FILE}"
import json
import sys
from pathlib import Path
payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
history_lines = Path(sys.argv[2]).read_text(encoding="utf-8").splitlines()
history_entry = json.loads(history_lines[-1])
assert payload["status"] == "failed"
assert payload["accepted"] is True
assert payload["error"] in {"check mock backend", "mock backend failed"}
assert payload["outcome"]["outcome_code"] == "execution_error"
assert payload["outcome"]["rc"] == 7
assert history_entry["status"] == "failed"
assert history_entry["error"] in {"check mock backend", "mock backend failed"}
assert len(history_lines) == 4
PY

ok "runtime_request submit persists append-only history, rejects duplicates, and fails safely"
echo "PASS: test_runtime_request_endpoint"
