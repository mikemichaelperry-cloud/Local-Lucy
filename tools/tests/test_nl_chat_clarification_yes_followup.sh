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
printf 'Q=%s\n' "${q}" >> "${CHAT_CALL_LOG}"
case "${q}" in
  "What's the latest local news?")
    printf '%s\n' 'Do you want Israel local delivery?'
    ;;
  "latest Israel news")
    printf '%s\n' 'From current sources:'
    ;;
  *)
    printf '%s\n' "unexpected:${q}"
    ;;
esac
SH
chmod +x "${CHAT_MOCK}"

printf '%b' "What's the latest local news?\nYes, please.\n/quit\n" \
  | CHAT_CALL_LOG="${LOGFILE}" LUCY_CHAT_BIN="${CHAT_MOCK}" "${NL_CHAT}" >/dev/null 2>&1 || true

[[ -s "${LOGFILE}" ]] || die "no chat calls logged"
first_q="$(sed -n '1p' "${LOGFILE}" | sed 's/^Q=//')"
second_q="$(sed -n '2p' "${LOGFILE}" | sed 's/^Q=//')"

[[ "${first_q}" == "What's the latest local news?" ]] || die "first query mismatch: ${first_q}"
[[ "${second_q}" == "latest Israel news" ]] || die "affirmative clarification follow-up not rewritten: ${second_q}"
ok "affirmative follow-up after Israel-local clarification maps to latest Israel news"

echo "PASS: test_nl_chat_clarification_yes_followup"
