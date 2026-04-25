#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"
WRITE_TOOL="${ROOT}/tools/write_local_lucy_handoff.sh"
RESUME_TOOL="${ROOT}/tools/resume_local_lucy_from_handoff.sh"

ok(){ echo "OK: $*"; }
die(){ echo "FAIL: $*" >&2; exit 1; }

[[ -x "${WRITE_TOOL}" ]] || die "missing handoff writer: ${WRITE_TOOL}"
[[ -x "${RESUME_TOOL}" ]] || die "missing handoff resume helper: ${RESUME_TOOL}"

TMPD="$(mktemp -d)"
trap 'rm -rf "${TMPD}"' EXIT

FAKE_ROOT="${TMPD}/root"
FAKE_UI="${TMPD}/ui"
FAKE_RUNTIME="${TMPD}/runtime-v7"
FAKE_STATE="${FAKE_RUNTIME}/state"

mkdir -p "${FAKE_ROOT}/tools" "${FAKE_ROOT}/dev_notes" "${FAKE_UI}" "${FAKE_STATE}"

cat > "${FAKE_STATE}/current_state.json" <<'EOF'
{
  "profile": "opt-experimental-v7-dev",
  "model": "local-lucy",
  "mode": "auto",
  "memory": "on",
  "evidence": "on",
  "voice": "off",
  "status": "ready",
  "last_updated": "2026-03-28T18:00:00Z"
}
EOF

cat > "${FAKE_STATE}/runtime_lifecycle.json" <<'EOF'
{
  "running": true,
  "status": "running",
  "pid": 12345,
  "last_error": ""
}
EOF

cat > "${FAKE_STATE}/last_request_result.json" <<'EOF'
{
  "completed_at": "2026-03-28T18:01:00Z",
  "request_id": "req-2",
  "request_text": "MJ4502 + MJ802 power darlington transistors. Are they in current production?",
  "status": "completed",
  "route": {
    "selected_route": "EVIDENCE"
  },
  "outcome": {
    "augmented_provider_used": "none",
    "trust_class": "evidence_backed",
    "outcome_code": "answered"
  }
}
EOF

cat > "${FAKE_STATE}/request_history.jsonl" <<'EOF'
{"request_id":"req-1"}
{"request_id":"req-2"}
EOF

first_write="$(
  LUCY_ROOT="${FAKE_ROOT}" \
  LUCY_UI_ROOT="${FAKE_UI}" \
  LUCY_RUNTIME_NAMESPACE_ROOT="${FAKE_RUNTIME}" \
  bash "${WRITE_TOOL}" --title "Test Handoff One" --session-summary "Initialized fake handoff flow|Validated baseline resume helper"
)"
first_path="$(printf '%s\n' "${first_write}" | sed -n 's/^OK: created Local Lucy handoff: //p')"
[[ -n "${first_path}" && -f "${first_path}" ]] || die "first handoff file missing"

sleep 1

second_write="$(
  LUCY_ROOT="${FAKE_ROOT}" \
  LUCY_UI_ROOT="${FAKE_UI}" \
  LUCY_RUNTIME_NAMESPACE_ROOT="${FAKE_RUNTIME}" \
  bash "${WRITE_TOOL}" --title "Test Handoff Two" --session-summary "Created a fresh timestamped handoff|Updated latest pointer|Validated newest handoff resolution"
)"
second_path="$(printf '%s\n' "${second_write}" | sed -n 's/^OK: created Local Lucy handoff: //p')"
[[ -n "${second_path}" && -f "${second_path}" ]] || die "second handoff file missing"
[[ "${first_path}" != "${second_path}" ]] || die "writer should create a fresh timestamped handoff each run"

pointer_path="${FAKE_ROOT}/dev_notes/LATEST_SESSION_HANDOFF.txt"
[[ -f "${pointer_path}" ]] || die "missing latest handoff pointer"
[[ "$(head -n1 "${pointer_path}")" == "${second_path}" ]] || die "latest handoff pointer should track newest file"

path_only="$(
  LUCY_ROOT="${FAKE_ROOT}" \
  bash "${RESUME_TOOL}" --path-only
)"
[[ "${path_only}" == "${second_path}" ]] || die "resume helper should resolve newest handoff path"

resume_out="$(
  LUCY_ROOT="${FAKE_ROOT}" \
  bash "${RESUME_TOOL}"
)"
printf '%s\n' "${resume_out}" | grep -Fq "${second_path}" || die "resume helper should print newest handoff path"
printf '%s\n' "${resume_out}" | grep -Fq "Session changes:" || die "resume helper should print session changes block"
printf '%s\n' "${resume_out}" | grep -Fq "Updated latest pointer" || die "resume helper should surface latest session changes"

grep -Fq "Previous handoff resumed: \`${first_path}\`" "${second_path}" || die "new handoff should reference prior handoff, not itself"
grep -Fq '**Completed through**: latest request/result snapshot at 2026-03-28T18:01:00Z' "${second_path}" || die "handoff should derive completed-through from live request state"
grep -Fq '## Session Changes' "${second_path}" || die "handoff should contain session changes section"
grep -Fq -- '- Updated latest pointer' "${second_path}" || die "handoff should record explicit session summary bullets"
grep -Fq '`last_request_route=EVIDENCE`' "${second_path}" || die "handoff should include latest request route"
grep -Fq '`last_request_outcome_code=answered`' "${second_path}" || die "handoff should include latest request outcome code"

ok "handoff writer creates fresh timestamped notes and updates latest pointer"
ok "resume helper resolves and prints the newest handoff"
echo "PASS: test_handoff_resume_latest"
