#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"
CHAT_BIN="${ROOT}/lucy_chat.sh"

ok(){ echo "OK: $*"; }
die(){ echo "FAIL: $*" >&2; exit 1; }

[[ -x "${CHAT_BIN}" ]] || die "missing lucy_chat.sh: ${CHAT_BIN}"

TMPD="$(mktemp -d)"
trap 'rm -rf "${TMPD}"' EXIT
MOCK_ROOT="${TMPD}/mock_root"

mkdir -p "${MOCK_ROOT}/tools" "${MOCK_ROOT}/config" "${MOCK_ROOT}/state"
printf 'demo_key_1\n' > "${MOCK_ROOT}/config/evidence_keys_allowlist.txt"

out="$(
  LUCY_ROOT="${MOCK_ROOT}" \
  LUCY_ROUTER_BYPASS=1 \
  LUCY_CHAT_FORCE_MODE=NEWS \
  LUCY_EVIDENCE_ENABLED=0 \
  "${CHAT_BIN}" "latest world news" 2>&1
)"

printf '%s\n' "${out}" | grep -q 'Evidence disabled by operator control.' || die "evidence-off gate did not emit operator-control message"
printf '%s\n' "${out}" | grep -q 'Enable evidence to allow news routes.' || die "evidence-off gate did not emit recovery guidance"

if find "${MOCK_ROOT}/evidence" -mindepth 1 -print -quit 2>/dev/null | grep -q .; then
  die "evidence-off gate should not create evidence session directories"
fi

ok "lucy_chat blocks non-local evidence/news execution when evidence control is off"
echo "PASS: test_lucy_chat_evidence_toggle_gate"
