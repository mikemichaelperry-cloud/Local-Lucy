#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"
PROFILE_TOOL="${ROOT}/tools/runtime_profile.py"

ok(){ echo "OK: $*"; }
die(){ echo "FAIL: $*" >&2; exit 1; }

[[ -f "${PROFILE_TOOL}" ]] || die "missing profile tool: ${PROFILE_TOOL}"

TMPD="$(mktemp -d)"
trap 'rm -rf "${TMPD}"' EXIT
STATE_FILE="${TMPD}/current_state.json"

python3 - <<'PY' "${STATE_FILE}"
import json
import sys
from pathlib import Path

state_path = Path(sys.argv[1])
state_path.write_text(
    json.dumps(
        {
            "profile": "stale-profile",
            "model": "stale-model",
            "mode": "offline",
            "memory": "off",
            "evidence": "off",
            "voice": "off",
            "approval_required": True,
            "status": "degraded",
            "last_updated": "2026-01-01T00:00:00Z",
        },
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)
PY

reload_json="$(
  LUCY_RUNTIME_PROFILE="profile-reloaded" \
  LUCY_RUNTIME_MODEL="model-reloaded" \
  python3 "${PROFILE_TOOL}" --state-file "${STATE_FILE}" reload
)"
show_json="$(python3 "${PROFILE_TOOL}" --state-file "${STATE_FILE}" show)"
noop_json="$(
  LUCY_RUNTIME_PROFILE="profile-reloaded" \
  LUCY_RUNTIME_MODEL="model-reloaded" \
  python3 "${PROFILE_TOOL}" --state-file "${STATE_FILE}" reload
)"

python3 - <<'PY' "${STATE_FILE}" "${reload_json}" "${show_json}" "${noop_json}"
import json
import sys
from pathlib import Path

state_path = Path(sys.argv[1])
reload_payload = json.loads(sys.argv[2])
show_payload = json.loads(sys.argv[3])
noop_payload = json.loads(sys.argv[4])
state = json.loads(state_path.read_text(encoding="utf-8"))

assert state["profile"] == "profile-reloaded"
assert state["model"] == "model-reloaded"
assert state["status"] == "ready"
assert state["mode"] == "offline"
assert state["memory"] == "off"
assert state["evidence"] == "off"
assert state["voice"] == "off"
assert state["approval_required"] is True
assert state["last_updated"]

assert reload_payload["ok"] is True
assert reload_payload["action"] == "reload"
assert reload_payload["changed"] is True
assert sorted(reload_payload["changed_fields"]) == ["model", "profile", "status"]

assert show_payload["ok"] is True
assert show_payload["action"] == "show"
assert show_payload["changed"] is False
assert show_payload["state"]["profile"] == "profile-reloaded"
assert show_payload["state"]["model"] == "model-reloaded"

assert noop_payload["ok"] is True
assert noop_payload["action"] == "reload"
assert noop_payload["changed"] is False
assert noop_payload["changed_fields"] == []
PY

ok "runtime_profile reload refreshes authoritative profile/model truth without mutating control toggles"
echo "PASS: test_runtime_profile_endpoint"
