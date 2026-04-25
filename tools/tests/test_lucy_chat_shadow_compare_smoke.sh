#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"
CHAT="${ROOT}/lucy_chat.sh"
LOGF="${ROOT}/tmp/logs/router_shadow_compare.log"

ok(){ echo "OK: $*"; }
die(){ echo "FAIL: $*" >&2; exit 1; }

[[ -x "${CHAT}" ]] || die "missing executable: ${CHAT}"

rm -f "${LOGF}"
out="$(
  LUCY_ROUTER_BYPASS=1 \
  LUCY_ROUTE_SHADOW_COMPARE=1 \
  LUCY_ROUTE_CONTROL_MODE=FORCED_OFFLINE \
  "${CHAT}" "Does tadalafil react with alcohol?" 2>&1
)"

printf '%s\n' "${out}" | grep -q "Insufficient evidence from trusted sources." \
  || die "expected deterministic medical insufficiency output in forced offline mode"
[[ -s "${LOGF}" ]] || die "expected shadow compare log file to be created"
grep -q 'status=' "${LOGF}" || die "expected status field in shadow compare log"
grep -q 'shadow_mode=' "${LOGF}" || die "expected shadow_mode field in shadow compare log"
grep -q 'final_mode=EVIDENCE' "${LOGF}" || die "expected final_mode=EVIDENCE in shadow compare log"
ok "lucy_chat shadow compare logs route comparison without changing behavior"

echo "PASS: test_lucy_chat_shadow_compare_smoke"
