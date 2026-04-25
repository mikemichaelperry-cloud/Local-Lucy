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

MODE_LOG="${TMPD}/voice_mode.log"

cat > "${MOCK_ROOT}/tools/lucy_voice_ptt.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "${LUCY_VOICE_ROUTE_MODE:-unset}" >> "${VOICE_MODE_LOG}"
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

run_case(){
  local label="$1"
  local input="$2"
  local expected="$3"
  local got

  got="$(
    printf '%b' "${input}" | \
      VOICE_MODE_LOG="${MODE_LOG}" \
      LUCY_RUNTIME_AUTHORITY_ROOT="${MOCK_ROOT}" \
      "${LAUNCHER}" >/dev/null 2>&1
    tail -n 1 "${MODE_LOG}"
  )"

  [[ "${got}" == "${expected}" ]] || die "${label}: expected ${expected}, got ${got}"
  ok "${label} -> ${got}"
}

run_case "auto default" "/voice-once\n/quit\n" "auto"
run_case "forced online" "/mode online\n/voice-once\n/quit\n" "online"
run_case "forced offline" "/mode offline\n/voice-once\n/quit\n" "offline"

echo "PASS: test_voice_launcher_mode_mapping"
