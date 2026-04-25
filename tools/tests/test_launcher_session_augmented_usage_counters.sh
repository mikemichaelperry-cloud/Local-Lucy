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
{
  echo "UTC=2026-03-25T07:00:00Z"
  echo "MODE=EVIDENCE"
  echo "ROUTE_REASON=mock_route"
  echo "SESSION_ID=mock-session"
  echo "QUERY=${q}"
} > "${LUCY_ROOT}/state/last_route.env"

if [[ "${q}" == "q1" ]]; then
  {
    echo "UTC=2026-03-25T07:00:01Z"
    echo "MODE=AUGMENTED"
    echo "ROUTE_REASON=mock_route"
    echo "SESSION_ID=mock-session"
    echo "EVIDENCE_CREATED=false"
    echo "OUTCOME_CODE=augmented_answer"
    echo "ACTION_HINT="
    echo "RC=0"
    echo "QUERY=${q}"
    echo "REQUESTED_MODE=AUGMENTED"
    echo "FINAL_MODE=AUGMENTED"
    echo "FALLBACK_USED=false"
    echo "FALLBACK_REASON=direct_request"
    echo "TRUST_CLASS=unverified"
    echo "AUGMENTED_PROVIDER=openai"
    echo "AUGMENTED_PROVIDER_SELECTED=openai"
    echo "AUGMENTED_PROVIDER_USED=openai"
    echo "AUGMENTED_PROVIDER_USAGE_CLASS=paid"
    echo "AUGMENTED_PROVIDER_CALL_REASON=direct"
    echo "AUGMENTED_PROVIDER_COST_NOTICE=true"
    echo "AUGMENTED_PAID_PROVIDER_INVOKED=true"
  } > "${LUCY_ROOT}/state/last_outcome.env"
elif [[ "${q}" == "q3" ]]; then
  {
    echo "UTC=2026-03-25T07:00:03Z"
    echo "MODE=AUGMENTED"
    echo "ROUTE_REASON=mock_route"
    echo "SESSION_ID=mock-session"
    echo "EVIDENCE_CREATED=true"
    echo "OUTCOME_CODE=augmented_fallback_answer"
    echo "ACTION_HINT="
    echo "RC=0"
    echo "QUERY=${q}"
    echo "REQUESTED_MODE=EVIDENCE"
    echo "FINAL_MODE=AUGMENTED"
    echo "FALLBACK_USED=true"
    echo "FALLBACK_REASON=validated_insufficient"
    echo "TRUST_CLASS=unverified"
    echo "AUGMENTED_PROVIDER=wikipedia"
    echo "AUGMENTED_PROVIDER_SELECTED=wikipedia"
    echo "AUGMENTED_PROVIDER_USED=wikipedia"
    echo "AUGMENTED_PROVIDER_USAGE_CLASS=free"
    echo "AUGMENTED_PROVIDER_CALL_REASON=fallback"
    echo "AUGMENTED_PROVIDER_COST_NOTICE=false"
    echo "AUGMENTED_PAID_PROVIDER_INVOKED=false"
  } > "${LUCY_ROOT}/state/last_outcome.env"
else
  {
    echo "UTC=2026-03-25T07:00:02Z"
    echo "MODE=EVIDENCE"
    echo "ROUTE_REASON=mock_route"
    echo "SESSION_ID=mock-session"
    echo "EVIDENCE_CREATED=true"
    echo "OUTCOME_CODE=answered"
    echo "ACTION_HINT="
    echo "RC=0"
    echo "QUERY=${q}"
    echo "REQUESTED_MODE=EVIDENCE"
    echo "FINAL_MODE=EVIDENCE"
    echo "FALLBACK_USED=false"
    echo "FALLBACK_REASON=none"
    echo "TRUST_CLASS=evidence_backed"
    echo "AUGMENTED_PROVIDER=none"
    echo "AUGMENTED_PROVIDER_SELECTED=none"
    echo "AUGMENTED_PROVIDER_USED=none"
    echo "AUGMENTED_PROVIDER_USAGE_CLASS=none"
    echo "AUGMENTED_PROVIDER_CALL_REASON=not_needed"
    echo "AUGMENTED_PROVIDER_COST_NOTICE=false"
    echo "AUGMENTED_PAID_PROVIDER_INVOKED=false"
  } > "${LUCY_ROOT}/state/last_outcome.env"
fi

printf 'BEGIN_VALIDATED\nmock response\nEND_VALIDATED\n'
SH
chmod +x "${MOCK_ROOT}/lucy_chat.sh"

out="$({
  printf 'q1\n'
  printf 'q2\n'
  printf 'q3\n'
  printf '/status\n'
  printf '/quit\n'
} | LUCY_RUNTIME_AUTHORITY_ROOT="${MOCK_ROOT}" "${LAUNCHER}" 2>&1)"

printf '%s\n' "${out}" | grep -q 'Session augmented calls: 2' || die "expected total augmented calls=2"
printf '%s\n' "${out}" | grep -q 'Session paid augmented calls: 1' || die "expected paid augmented calls=1"
printf '%s\n' "${out}" | grep -q 'Session provider calls: openai=1 grok=0 wikipedia=1' || die "expected per-provider counts openai=1 grok=0 wikipedia=1"

ok "launcher tracks session-level augmented usage counters from authoritative outcome metadata"
echo "PASS: test_launcher_session_augmented_usage_counters"
