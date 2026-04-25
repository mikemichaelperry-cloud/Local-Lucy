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

cat > "${MOCK_ROOT}/tools/lucy_voice_ptt.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
echo "mock voice once"
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

cat > "${MOCK_ROOT}/tools/health_battery.sh" <<'SH'
#!/usr/bin/env bash
exit 0
SH
chmod +x "${MOCK_ROOT}/tools/health_battery.sh"

cat > "${MOCK_ROOT}/lucy_chat.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf 'CHAT:%s\n' "$*"
SH
chmod +x "${MOCK_ROOT}/lucy_chat.sh"

out_file="${TMPD}/launcher.out"
input_file="${TMPD}/launcher.in"
printf '/voice-once\n/quit\n' > "${input_file}"

cat "${input_file}" | \
  LUCY_RUNTIME_AUTHORITY_ROOT="${MOCK_ROOT}" \
  "${LAUNCHER}" >"${out_file}" 2>&1

if grep -q '^CHAT:' "${out_file}"; then
  die "launcher unexpectedly routed a one-shot voice control turn into chat"
fi
grep -q 'One-shot exits automatically after the answer.' "${out_file}" || die "missing one-shot guidance"

ok "launcher keeps one-shot voice launch isolated from chat input in non-tty mode"
echo "PASS: test_voice_once_launcher_discards_post_voice_residual_input"
