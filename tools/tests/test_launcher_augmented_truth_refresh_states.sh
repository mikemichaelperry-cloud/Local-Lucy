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
  echo "UTC=2026-03-23T20:00:00Z"
  echo "MODE=EVIDENCE"
  echo "ROUTE_REASON=mock_route"
  echo "SESSION_ID=mock-session"
  echo "QUERY=${q}"
} > "${LUCY_ROOT}/state/last_route.env"

if [[ "${LUCY_AUGMENTED_DIRECT_REQUEST:-0}" == "1" ]]; then
  {
    echo "UTC=2026-03-23T20:00:01Z"
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
    echo "AUGMENTED_PROVIDER=wikipedia"
    echo "AUGMENTATION_POLICY=${LUCY_AUGMENTATION_POLICY:-disabled}"
  } > "${LUCY_ROOT}/state/last_outcome.env"
  printf 'BEGIN_VALIDATED\nAugmented mode (unverified answer):\nmock direct\nEND_VALIDATED\n'
  exit 0
fi

if [[ "${q}" == "evidence answered" ]]; then
  {
    echo "UTC=2026-03-23T20:00:01Z"
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
    echo "AUGMENTATION_POLICY=${LUCY_AUGMENTATION_POLICY:-disabled}"
  } > "${LUCY_ROOT}/state/last_outcome.env"
  printf 'BEGIN_VALIDATED\nFrom current sources:\nmock evidence answer\nEND_VALIDATED\n'
  exit 0
fi

if [[ "${q}" == "evidence insufficient" ]]; then
  {
    echo "UTC=2026-03-23T20:00:01Z"
    echo "MODE=EVIDENCE"
    echo "ROUTE_REASON=mock_route"
    echo "SESSION_ID=mock-session"
    echo "EVIDENCE_CREATED=true"
    echo "OUTCOME_CODE=validated_insufficient"
    echo "ACTION_HINT="
    echo "RC=0"
    echo "QUERY=${q}"
    echo "REQUESTED_MODE=EVIDENCE"
    echo "FINAL_MODE=EVIDENCE"
    echo "FALLBACK_USED=false"
    echo "FALLBACK_REASON=none"
    echo "TRUST_CLASS=evidence_backed"
    echo "AUGMENTED_PROVIDER=none"
    echo "AUGMENTATION_POLICY=${LUCY_AUGMENTATION_POLICY:-disabled}"
  } > "${LUCY_ROOT}/state/last_outcome.env"
  printf 'BEGIN_VALIDATED\nInsufficient evidence from trusted sources.\nEND_VALIDATED\n'
  exit 0
fi

{
  echo "UTC=2026-03-23T20:00:01Z"
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
  echo "AUGMENTATION_POLICY=${LUCY_AUGMENTATION_POLICY:-disabled}"
} > "${LUCY_ROOT}/state/last_outcome.env"
printf 'BEGIN_VALIDATED\nAugmented fallback (unverified answer):\nmock fallback\nEND_VALIDATED\n'
SH
chmod +x "${MOCK_ROOT}/lucy_chat.sh"

out="$({
  printf 'evidence answered\n'
  printf '/why\n'
  printf 'evidence insufficient\n'
  printf '/why\n'
  printf '/augmented fallback_only\n'
  printf 'evidence fallback\n'
  printf '/why\n'
  printf '/augmented direct_allowed\n'
  printf 'run augmented: direct request\n'
  printf '/why\n'
  printf '/quit\n'
} | LUCY_RUNTIME_AUTHORITY_ROOT="${MOCK_ROOT}" "${LAUNCHER}" 2>&1)"

printf '%s\n' "${out}" | grep -q 'Outcome code: answered' || die "missing evidence answered outcome"
printf '%s\n' "${out}" | grep -q 'Answer summary: Evidence-backed' || die "missing evidence-backed summary label"
printf '%s\n' "${out}" | grep -q 'Augmented provider: none' || die "missing provider metadata for evidence answer"
printf '%s\n' "${out}" | grep -q 'Final mode: EVIDENCE' || die "missing EVIDENCE final mode"
printf '%s\n' "${out}" | grep -q 'Trust class: evidence_backed' || die "missing evidence trust class"

printf '%s\n' "${out}" | grep -q 'Outcome code: validated_insufficient' || die "missing validated_insufficient outcome"
printf '%s\n' "${out}" | grep -q 'Answer summary: Insufficient evidence' || die "missing insufficient summary label"

printf '%s\n' "${out}" | grep -q 'Outcome code: augmented_fallback_answer' || die "missing augmented fallback outcome"
printf '%s\n' "${out}" | grep -q 'Answer summary: Augmented fallback (not verified)' || die "missing augmented fallback summary label"
printf '%s\n' "${out}" | grep -q 'Augmented provider: wikipedia' || die "missing provider metadata for augmented fallback"
printf '%s\n' "${out}" | grep -q 'Fallback reason: validated_insufficient' || die "missing fallback reason refresh"

printf '%s\n' "${out}" | grep -q 'Outcome code: augmented_answer' || die "missing direct augmented outcome"
printf '%s\n' "${out}" | grep -q 'Answer summary: Augmented (not verified)' || die "missing direct augmented summary label"
printf '%s\n' "${out}" | grep -q 'Augmented provider: wikipedia' || die "missing provider metadata for direct augmented"
printf '%s\n' "${out}" | grep -q 'Requested mode: AUGMENTED' || die "missing direct augmented requested mode"
printf '%s\n' "${out}" | grep -q 'Final mode: AUGMENTED' || die "missing direct augmented final mode"

ok "launcher truth metadata refreshes across evidence, fallback, and direct augmented flows"
echo "PASS: test_launcher_augmented_truth_refresh_states"
