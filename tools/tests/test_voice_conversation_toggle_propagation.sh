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
mkdir -p "${MOCK_ROOT}/tools" "${MOCK_ROOT}/tmp" "${MOCK_ROOT}/state"
VOICE_LOG="${TMPD}/voice_toggle.log"

cat > "${MOCK_ROOT}/tools/lucy_voice_ptt.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf 'mode=%s conv=%s\n' "${LUCY_VOICE_ROUTE_MODE:-unset}" "${LUCY_CONVERSATION_MODE_FORCE:-unset}" >> "${LUCY_TEST_VOICE_LOG_FILE}"
exit 0
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

printf '/conversation on\n/voice-once\n/conversation off\n/voice-once\n/quit\n' | \
  LUCY_RUNTIME_AUTHORITY_ROOT="${MOCK_ROOT}" \
  LUCY_TEST_VOICE_LOG_FILE="${VOICE_LOG}" \
  "${LAUNCHER}" >/dev/null 2>&1

line1="$(sed -n '1p' "${VOICE_LOG}")"
line2="$(sed -n '2p' "${VOICE_LOG}")"
[[ "${line1}" == "mode=auto conv=1" ]] || die "expected first voice turn mode=auto conv=1, got: ${line1}"
[[ "${line2}" == "mode=auto conv=0" ]] || die "expected second voice turn mode=auto conv=0, got: ${line2}"
ok "voice launcher propagates conversation toggle into voice env"

echo "PASS: test_voice_conversation_toggle_propagation"
