#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"
LAUNCHER="${ROOT}/tools/start_local_lucy_opt_experimental_v7_dev.sh"

ok(){ echo "OK: $*"; }
die(){ echo "FAIL: $*" >&2; exit 1; }

[[ -x "${LAUNCHER}" ]] || die "missing executable: ${LAUNCHER}"

TMPD="$(mktemp -d)"
trap 'rm -rf "${TMPD}"' EXIT

MOCK_ROOT="${TMPD}/mock_root"
PROMPT_FILE="${TMPD}/preprocess_prompt.txt"
ESCALATION_LOG="${TMPD}/escalation.log"
mkdir -p "${MOCK_ROOT}/tools" "${MOCK_ROOT}/tmp" "${MOCK_ROOT}/state"

cat > "${MOCK_ROOT}/lucy_chat.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
cat > "${LUCY_ROOT}/state/last_outcome.env" <<EOF
UTC=2026-03-18T20:00:00+00:00
MODE=CLARIFY
ROUTE_REASON=router_classifier_mapper
SESSION_ID=
EVIDENCE_CREATED=false
OUTCOME_CODE=clarification_requested
ACTION_HINT=
RC=0
QUERY=${1:-}
GOVERNOR_REQUIRES_CLARIFICATION=true
EOF
printf 'To implement a task, we need more information about what needs to be done.\n'
SH
chmod +x "${MOCK_ROOT}/lucy_chat.sh"

cat > "${PROMPT_FILE}" <<'EOF'
Active root: /tmp/mock
Task: Finish the handed-off implementation locally if possible.
Likely files: tools/start_local_lucy_opt_experimental_v3_dev.sh
EOF

cat > "${TMPD}/fake_codex_launcher.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf 'ARGS=%s\n' "$*" >> "${LUCY_TEST_ESCALATION_LOG}"
printf 'TASK=%s\n' "${LUCY_CODEX_PREPROCESS_TASK:-}" >> "${LUCY_TEST_ESCALATION_LOG}"
printf 'REASON=%s\n' "${LUCY_CODEX_ESCALATION_REASON:-}" >> "${LUCY_TEST_ESCALATION_LOG}"
printf 'PROMPT=%s\n' "${LUCY_CODEX_PREPROCESS_PROMPT_PATH:-}" >> "${LUCY_TEST_ESCALATION_LOG}"
exit 0
SH
chmod +x "${TMPD}/fake_codex_launcher.sh"

out="$(LUCY_RUNTIME_AUTHORITY_ROOT="${MOCK_ROOT}" \
  LUCY_CODEX_LAUNCHER_PATH="${TMPD}/fake_codex_launcher.sh" \
  LUCY_TEST_ESCALATION_LOG="${ESCALATION_LOG}" \
  LUCY_CODEX_GATE_DECISION="local_only" \
  LUCY_CODEX_PREPROCESS_TASK="Finish the handed-off implementation locally if possible." \
  LUCY_CODEX_PREPROCESS_PROMPT_PATH="${PROMPT_FILE}" \
  "${LAUNCHER}" 2>&1)"

printf '%s\n' "${out}" | grep -q 'Running preprocess task from Codex Launcher\.' || die "preprocess autorun notice missing"
printf '%s\n' "${out}" | grep -q 'Escalating to Codex\.' || die "escalation notice missing"
[[ -s "${ESCALATION_LOG}" ]] || die "expected escalation launcher to be invoked"

escalation_log="$(<"${ESCALATION_LOG}")"
[[ "${escalation_log}" == *"ARGS=--run-codex-preprocess-escalation"* ]] || die "unexpected escalation launcher args"
[[ "${escalation_log}" == *"TASK=Finish the handed-off implementation locally if possible."* ]] || die "escalation did not preserve preprocess task"
[[ "${escalation_log}" == *"REASON=Lucy requested clarification instead of completing the handed-off task."* ]] || die "escalation reason mismatch"
[[ "${escalation_log}" == *"PROMPT=${PROMPT_FILE}"* ]] || die "escalation did not preserve prompt path"

ok "launcher escalates preprocess local-only tasks to Codex when Lucy requests clarification"
echo "PASS: test_launcher_preprocess_escalation"
