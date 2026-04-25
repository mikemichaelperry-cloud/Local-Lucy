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
LOG_FILE="${TMPD}/launcher_conv.log"

cat > "${MOCK_ROOT}/lucy_chat.sh" <<'SH2'
#!/usr/bin/env bash
set -euo pipefail
printf 'q=%s conv=%s\n' "${1:-}" "${LUCY_CONVERSATION_MODE_FORCE:-unset}" >> "${LUCY_TEST_LOG_FILE}"
printf 'ok\n'
SH2
chmod +x "${MOCK_ROOT}/lucy_chat.sh"

printf '/conversation on\nhello\n/conversation off\nhello\n/quit\n' | \
  LUCY_RUNTIME_AUTHORITY_ROOT="${MOCK_ROOT}" \
  LUCY_TEST_LOG_FILE="${LOG_FILE}" \
  "${LAUNCHER}" >/dev/null 2>&1

line1="$(sed -n '1p' "${LOG_FILE}")"
line2="$(sed -n '2p' "${LOG_FILE}")"
[[ "${line1}" == "q=hello conv=1" ]] || die "expected first query with conv=1, got: ${line1}"
[[ "${line2}" == "q=hello conv=0" ]] || die "expected second query with conv=0, got: ${line2}"
ok "launcher conversation toggle propagates LUCY_CONVERSATION_MODE_FORCE"

echo "PASS: launcher_conversation_toggle"
