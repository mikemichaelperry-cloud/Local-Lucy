#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"
NL_CHAT="${ROOT}/tools/lucy_nl_chat.sh"

ok(){ echo "OK: $*"; }
die(){ echo "FAIL: $*" >&2; exit 1; }

[[ -x "${NL_CHAT}" ]] || die "missing executable: ${NL_CHAT}"

TMPD="$(mktemp -d)"
trap 'rm -rf "${TMPD}"' EXIT
CHAT_MOCK="${TMPD}/mock_chat.sh"
LOGFILE="${TMPD}/chat_calls.log"

cat > "${CHAT_MOCK}" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
q="${1:-}"
mem="${LUCY_CHAT_MEMORY_FILE:-}"
printf 'Q=%s\tMEM=%s\n' "$q" "$mem" >> "${CHAT_CALL_LOG}"
printf 'mock answer for: %s\n' "$q"
SH
chmod +x "${CHAT_MOCK}"

run_case() {
  local label="$1"
  local input="$2"
  : > "${LOGFILE}"
  printf '%b' "${input}" | CHAT_CALL_LOG="${LOGFILE}" LUCY_CHAT_BIN="${CHAT_MOCK}" "${NL_CHAT}" >/dev/null 2>&1 || true
  [[ -s "${LOGFILE}" ]] || die "${label}: no chat calls logged"
}

# Local conversational turns should use and persist memory.
run_case "local_memory_on" "hello\nwhat is lm317?\n/quit\n"
first_mem="$(awk -F'\t' 'NR==1{print $2}' "${LOGFILE}" | sed 's/^MEM=//')"
second_mem="$(awk -F'\t' 'NR==2{print $2}' "${LOGFILE}" | sed 's/^MEM=//')"
[[ -n "${first_mem}" ]] || die "local_memory_on: first turn missing memory file"
[[ -n "${second_mem}" ]] || die "local_memory_on: second turn missing memory file"
[[ "${first_mem}" == "${second_mem}" ]] || die "local_memory_on: memory file not stable across local turns"
ok "local turns use persistent memory"

# News/evidence/time-sensitive turns should bypass chat memory to avoid contamination.
run_case "news_memory_bypass" "latest Israeli news\n/quit\n"
news_mem="$(awk -F'\t' 'NR==1{print $2}' "${LOGFILE}" | sed 's/^MEM=//')"
[[ -z "${news_mem}" ]] || die "news_memory_bypass: news turn unexpectedly used chat memory"
ok "news turn bypasses chat memory"

run_case "evidence_memory_bypass" "Who is considered the latest Shah of Iran?\n/quit\n"
evid_mem="$(awk -F'\t' 'NR==1{print $2}' "${LOGFILE}" | sed 's/^MEM=//')"
[[ -z "${evid_mem}" ]] || die "evidence_memory_bypass: evidence/time-sensitive turn unexpectedly used chat memory"
ok "time-sensitive/evidence turn bypasses chat memory"

run_case "medical_memory_bypass" "Does tadalifil react with alcohol?\n/quit\n"
med_mem="$(awk -F'\t' 'NR==1{print $2}' "${LOGFILE}" | sed 's/^MEM=//')"
[[ -z "${med_mem}" ]] || die "medical_memory_bypass: medical/high-risk turn unexpectedly used chat memory"
ok "medical/high-risk turn bypasses chat memory"

echo "PASS: test_nl_chat_memory_isolation"
