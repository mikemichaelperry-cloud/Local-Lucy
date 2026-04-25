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
mkdir -p "${MOCK_ROOT}/state" "${MOCK_ROOT}/tools" "${MOCK_ROOT}/tmp"

cat > "${MOCK_ROOT}/lucy_chat.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
q="${1:-}"
mkdir -p "${LUCY_ROOT}/state"
if [[ "${q}" == "good" ]]; then
  cat > "${LUCY_ROOT}/state/last_route.env" <<EOF
UTC=2026-03-23T22:00:00Z
MODE=EVIDENCE
ROUTE_REASON=mock_route
SESSION_ID=good-session
QUERY=${q}
EOF
  cat > "${LUCY_ROOT}/state/last_outcome.env" <<EOF
UTC=2026-03-23T22:00:01Z
MODE=EVIDENCE
ROUTE_REASON=mock_route
SESSION_ID=good-session
EVIDENCE_CREATED=true
OUTCOME_CODE=answered
ACTION_HINT=
RC=0
QUERY=${q}
REQUESTED_MODE=EVIDENCE
FINAL_MODE=EVIDENCE
FALLBACK_USED=false
FALLBACK_REASON=none
TRUST_CLASS=evidence_backed
EOF
  printf 'BEGIN_VALIDATED\ngood reply\nEND_VALIDATED\n'
  exit 0
fi
printf 'backend exploded\n' >&2
exit 7
SH
chmod +x "${MOCK_ROOT}/lucy_chat.sh"

out="$({
  printf 'good\n'
  printf 'bad\n'
  printf '/why\n'
  printf '/status\n'
  printf '/quit\n'
} | LUCY_RUNTIME_AUTHORITY_ROOT="${MOCK_ROOT}" "${LAUNCHER}" 2>&1)"

count_answered="$(printf '%s\n' "${out}" | grep -c '^Outcome code: answered$' || true)"
[[ "${count_answered}" == "1" ]] || die "stale answered truth leaked into failed request output"
printf '%s\n' "${out}" | grep -q '^Outcome code: execution_error$' || die "missing synthesized execution_error outcome"
printf '%s\n' "${out}" | grep -q '^Final mode: ERROR$' || die "missing synthesized ERROR final mode"
printf '%s\n' "${out}" | grep -q '^Trust class: unknown$' || die "missing synthesized unknown trust class"
printf '%s\n' "${out}" | grep -q '^backend exploded$' || die "missing backend failure text"
printf '%s\n' "${out}" | grep -q '^Answer: Execution error$' || die "missing failure truth summary"
printf '%s\n' "${out}" | grep -q '^Answer trust: unknown$' || die "missing /status unknown trust state"
printf '%s\n' "${out}" | grep -q 'Last backend error: backend exploded' || die "missing backend error reflection"

ok "launcher does not reuse stale truth metadata after backend failure"
echo "PASS: test_launcher_backend_failure_does_not_reuse_stale_truth"
