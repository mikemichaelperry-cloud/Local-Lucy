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
FAKE_ROOT="${TMPD}/root"
LOGFILE="${TMPD}/calls.log"
mkdir -p "${FAKE_ROOT}/tools" "${FAKE_ROOT}/tmp/run" "${FAKE_ROOT}/state" "${FAKE_ROOT}/evidence"

cat > "${FAKE_ROOT}/lucy_chat.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf 'Q=%s\tMEM=%s\tMODE=%s\n' "${1:-}" "${LUCY_CHAT_MEMORY_FILE:-}" "${LUCY_ROUTE_CONTROL_MODE:-}" >> "${LAUNCHER_CHAT_LOG}"
echo "mock-response"
SH
chmod +x "${FAKE_ROOT}/lucy_chat.sh"

# Stubs so launcher command checks won't fail if invoked.
for f in install_voice_engines.sh verify_voice_engines.sh lucy_voice_ptt.sh; do
  cat > "${FAKE_ROOT}/tools/${f}" <<'SH'
#!/usr/bin/env bash
exit 0
SH
  chmod +x "${FAKE_ROOT}/tools/${f}"
done

run_case() {
  local label="$1"
  local input="$2"
  : > "${LOGFILE}"
  printf '%b' "${input}" | LAUNCHER_CHAT_LOG="${LOGFILE}" LUCY_RUNTIME_AUTHORITY_ROOT="${FAKE_ROOT}" "${LAUNCHER}" >/dev/null 2>&1 || true
  [[ -s "${LOGFILE}" ]] || die "${label}: no lucy_chat calls logged"
}

run_case "local_then_local" "hello\nwhat is lm317?\n/quit\n"
m1="$(awk -F'\t' 'NR==1{print $2}' "${LOGFILE}" | sed 's/^MEM=//')"
m2="$(awk -F'\t' 'NR==2{print $2}' "${LOGFILE}" | sed 's/^MEM=//')"
[[ -n "${m1}" && -n "${m2}" ]] || die "local_then_local: expected memory on local turns"
[[ "${m1}" == "${m2}" ]] || die "local_then_local: memory file changed across local turns"
ok "launcher local turns use session memory"

run_case "news_bypass" "Whats the latest Israel news?\n/quit\n"
news_mem="$(awk -F'\t' 'NR==1{print $2}' "${LOGFILE}" | sed 's/^MEM=//')"
[[ -z "${news_mem}" ]] || die "news_bypass: news turn unexpectedly used session memory"
ok "launcher bypasses memory for news"

run_case "medical_bypass" "Does tadalifil react with alcohol?\n/quit\n"
med_mem="$(awk -F'\t' 'NR==1{print $2}' "${LOGFILE}" | sed 's/^MEM=//')"
[[ -z "${med_mem}" ]] || die "medical_bypass: medical turn unexpectedly used session memory"
ok "launcher bypasses memory for medical/high-risk queries"

echo "PASS: test_launcher_memory_isolation"
