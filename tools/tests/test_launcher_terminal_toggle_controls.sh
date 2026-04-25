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
OUT_FILE="${TMPD}/launcher.out"
VOICE_LOG="${TMPD}/voice.log"
mkdir -p "${MOCK_ROOT}/tools" "${MOCK_ROOT}/tmp" "${MOCK_ROOT}/state"

cat > "${MOCK_ROOT}/tools/lucy_voice_ptt.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf 'mode=%s\n' "${LUCY_VOICE_ROUTE_MODE:-unset}" >> "${LUCY_TEST_VOICE_LOG_FILE}"
echo "mock voice once"
exit 0
SH
chmod +x "${MOCK_ROOT}/tools/lucy_voice_ptt.sh"

for tool in install_voice_engines.sh verify_voice_engines.sh; do
  cat > "${MOCK_ROOT}/tools/${tool}" <<'SH'
#!/usr/bin/env bash
exit 0
SH
  chmod +x "${MOCK_ROOT}/tools/${tool}"
done

printf '%b' '/help\n/evidence off\n/evidence mode\n/evidence on\n/evidence mode\n/voice off\n/voice mode\n/voice-once\n/voice on\n/voice mode\n/voice-once\n/quit\n' \
  | LUCY_RUNTIME_AUTHORITY_ROOT="${MOCK_ROOT}" \
    LUCY_TEST_VOICE_LOG_FILE="${VOICE_LOG}" \
    "${LAUNCHER}" > "${OUT_FILE}" 2>&1

grep -q 'evidence on|off' "${OUT_FILE}" || die "help output missing evidence toggle docs"
grep -q 'voice on|off' "${OUT_FILE}" || die "help output missing voice toggle docs"
grep -q 'Evidence control: OFF' "${OUT_FILE}" || die "expected evidence off feedback"
grep -q 'Evidence control: ON' "${OUT_FILE}" || die "expected evidence on feedback"
grep -q 'Voice control: OFF' "${OUT_FILE}" || die "expected voice off feedback"
grep -q 'Voice disabled by operator control.' "${OUT_FILE}" || die "voice-off should block /voice-once"
grep -q 'Voice control: ON' "${OUT_FILE}" || die "expected voice on feedback"
[[ "$(wc -l < "${VOICE_LOG}")" == "1" ]] || die "expected exactly one real voice invocation after re-enable"
grep -qx 'mode=auto' "${VOICE_LOG}" || die "expected enabled one-shot voice to retain auto route mode"

ok "launcher exposes evidence and voice terminal toggles and enforces them"
echo "PASS: test_launcher_terminal_toggle_controls"
