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
printf '%s\n' "ok"
SH
chmod +x "${MOCK_ROOT}/lucy_chat.sh"

cat > "${MOCK_ROOT}/state/last_outcome.env" <<'ENV'
MODE=AUGMENTED
ROUTE_REASON=router_classifier_mapper
OUTCOME_CODE=augmented_fallback_answer
REQUESTED_MODE=EVIDENCE
FINAL_MODE=AUGMENTED
FALLBACK_USED=true
FALLBACK_REASON=validated_insufficient
TRUST_CLASS=unverified
EVIDENCE_CREATED=true
MANIFEST_EVIDENCE_MODE=FULL
MANIFEST_EVIDENCE_MODE_REASON=explicit_source_request
AUGMENTED_ALLOWED=true
AUGMENTED_PROVIDER_SELECTED=openai
AUGMENTED_PROVIDER_USED=openai
AUGMENTED_PROVIDER_USAGE_CLASS=paid
AUGMENTED_PROVIDER_CALL_REASON=fallback
AUGMENTED_PROVIDER_COST_NOTICE=true
AUGMENTED_PAID_PROVIDER_INVOKED=true
ENV

out="$({
  printf '/why\n'
  printf '/status\n'
  printf '/quit\n'
} | LUCY_RUNTIME_AUTHORITY_ROOT="${MOCK_ROOT}" LUCY_AUGMENTATION_POLICY="direct_allowed" LUCY_AUGMENTED_PROVIDER="openai" OPENAI_API_KEY="test-key" "${LAUNCHER}" 2>&1)"

printf '%s\n' "${out}" | grep -q 'Requested mode: EVIDENCE' || die "missing requested mode in /why"
printf '%s\n' "${out}" | grep -q 'Final mode: AUGMENTED' || die "missing final mode in /why"
printf '%s\n' "${out}" | grep -q 'Fallback used: true' || die "missing fallback_used in /why"
printf '%s\n' "${out}" | grep -q 'Fallback reason: validated_insufficient' || die "missing fallback_reason in /why"
printf '%s\n' "${out}" | grep -q 'Trust class: unverified' || die "missing trust class in /why"
printf '%s\n' "${out}" | grep -q 'Evidence mode: FULL' || die "missing evidence mode in /why"
printf '%s\n' "${out}" | grep -q 'Evidence mode reason: explicit_source_request' || die "missing evidence mode reason in /why"
printf '%s\n' "${out}" | grep -q 'Evidence mode selection: explicit-user-triggered' || die "missing evidence mode selection in /why"
printf '%s\n' "${out}" | grep -q 'Augmented allowed: true' || die "missing augmented allowed in /why"
printf '%s\n' "${out}" | grep -q 'Provider used: openai' || die "missing provider used in /why"
printf '%s\n' "${out}" | grep -q 'Provider call reason: fallback' || die "missing provider call reason in /why"
printf '%s\n' "${out}" | grep -q 'Paid provider invocation: true' || die "missing paid invocation flag in /why"
printf '%s\n' "${out}" | grep -q 'Augmented policy: direct_allowed' || die "missing augmented policy in HMI output"
printf '%s\n' "${out}" | grep -q 'Selected provider usage profile: paid/unverified' || die "missing provider usage profile in /status"
printf '%s\n' "${out}" | grep -q 'Selected provider API key: present' || die "missing provider API-key state in /status"
printf '%s\n' "${out}" | grep -q 'Last provider used: openai' || die "missing last provider used in /status"
printf '%s\n' "${out}" | grep -q 'Last outcome code: augmented_fallback_answer' || die "missing last outcome code in /status"
printf '%s\n' "${out}" | grep -q 'Answer trust: unverified' || die "missing trust badge in /status"

ok "launcher reflects requested/final mode and trust metadata"
echo "PASS: test_launcher_why_augmented_truth_reflection"
