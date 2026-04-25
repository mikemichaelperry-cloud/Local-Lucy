#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"
LAUNCHER="${ROOT}/tools/start_local_lucy_opt_experimental_v7_dev.sh"
CONTROL_TOOL="${ROOT}/tools/runtime_control.py"

ok(){ echo "OK: $*"; }
die(){ echo "FAIL: $*" >&2; exit 1; }

[[ -x "${LAUNCHER}" ]] || die "missing launcher: ${LAUNCHER}"
[[ -f "${CONTROL_TOOL}" ]] || die "missing control tool: ${CONTROL_TOOL}"

TMPD="$(mktemp -d)"
trap 'rm -rf "${TMPD}"' EXIT

STATE_FILE="${TMPD}/current_state.json"
MOCK_ROOT="${TMPD}/mock_root"
CHAT_LOG="${TMPD}/chat_env.log"
VOICE_LOG="${TMPD}/voice_env.log"

mkdir -p "${MOCK_ROOT}/tools" "${MOCK_ROOT}/tmp" "${MOCK_ROOT}/state"

cat > "${MOCK_ROOT}/lucy_chat.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf 'route=%s memory=%s evidence=%s\n' \
  "${LUCY_ROUTE_CONTROL_MODE:-unset}" \
  "${LUCY_SESSION_MEMORY:-unset}" \
  "${LUCY_EVIDENCE_ENABLED:-unset}" >> "${CHAT_LOG_FILE}"
printf 'aug_policy=%s aug_provider=%s\n' \
  "${LUCY_AUGMENTATION_POLICY:-unset}" \
  "${LUCY_AUGMENTED_PROVIDER:-unset}" >> "${CHAT_LOG_FILE}"
printf 'mock answer\n'
SH
chmod +x "${MOCK_ROOT}/lucy_chat.sh"

cat > "${MOCK_ROOT}/tools/lucy_voice_ptt.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf 'voice invoked\n' >> "${VOICE_LOG_FILE}"
SH
chmod +x "${MOCK_ROOT}/tools/lucy_voice_ptt.sh"

cat > "${MOCK_ROOT}/tools/install_voice_engines.sh" <<'SH'
#!/usr/bin/env bash
exit 0
SH
chmod +x "${MOCK_ROOT}/tools/install_voice_engines.sh"

cat > "${MOCK_ROOT}/tools/verify_voice_engines.sh" <<'SH'
#!/usr/bin/env bash
exit 0
SH
chmod +x "${MOCK_ROOT}/tools/verify_voice_engines.sh"

python3 "${CONTROL_TOOL}" --state-file "${STATE_FILE}" ensure-state >/dev/null
python3 "${CONTROL_TOOL}" --state-file "${STATE_FILE}" set-mode --value offline >/dev/null
python3 "${CONTROL_TOOL}" --state-file "${STATE_FILE}" set-memory --value off >/dev/null
python3 "${CONTROL_TOOL}" --state-file "${STATE_FILE}" set-evidence --value off >/dev/null
python3 "${CONTROL_TOOL}" --state-file "${STATE_FILE}" set-voice --value off >/dev/null
python3 "${CONTROL_TOOL}" --state-file "${STATE_FILE}" set-augmentation --value direct_allowed >/dev/null
python3 "${CONTROL_TOOL}" --state-file "${STATE_FILE}" set-augmented-provider --value openai >/dev/null

out="$(
  {
    printf '/status\n'
    printf 'hello world\n'
    printf '/voice-once\n'
    printf '/quit\n'
  } | CHAT_LOG_FILE="${CHAT_LOG}" \
      VOICE_LOG_FILE="${VOICE_LOG}" \
      LUCY_RUNTIME_AUTHORITY_ROOT="${MOCK_ROOT}" \
      LUCY_RUNTIME_CONTROL_FORCE=1 \
      LUCY_RUNTIME_STATE_FILE="${STATE_FILE}" \
      "${LAUNCHER}" 2>&1
)"

printf '%s\n' "${out}" | grep -q 'Mode: offline (forced; web blocked, medical returns offline insufficiency)' || die "launcher status did not reflect authoritative mode"
printf '%s\n' "${out}" | grep -q 'Session memory: off' || die "launcher status did not reflect authoritative memory state"
printf '%s\n' "${out}" | grep -q 'Evidence control: off' || die "launcher status did not reflect authoritative evidence state"
printf '%s\n' "${out}" | grep -q 'Voice control: off' || die "launcher status did not reflect authoritative voice state"
printf '%s\n' "${out}" | grep -q 'Augmented policy: direct_allowed' || die "launcher status did not reflect authoritative augmentation policy"
printf '%s\n' "${out}" | grep -q 'Selected augmented provider: openai' || die "launcher status did not reflect authoritative augmented provider"
printf '%s\n' "${out}" | grep -q 'Voice disabled by operator control.' || die "voice launch should be blocked when voice is off"

grep -qx 'route=FORCED_OFFLINE memory=0 evidence=0' "${CHAT_LOG}" || die "chat invocation did not inherit authoritative control env"
grep -qx 'aug_policy=direct_allowed aug_provider=openai' "${CHAT_LOG}" || die "chat invocation did not inherit authoritative augmentation env"
if [[ -s "${VOICE_LOG}" ]]; then
  die "voice tool should not have been invoked while voice is off"
fi

ok "launcher syncs persisted authoritative state and blocks disabled voice"
echo "PASS: test_launcher_authoritative_state_sync"
