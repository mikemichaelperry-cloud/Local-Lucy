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
  echo "AUGMENTED_PROVIDER=grok"
  echo "AUGMENTATION_POLICY=${LUCY_AUGMENTATION_POLICY:-disabled}"
  echo "UNVERIFIED_CONTEXT_USED=true"
  echo "UNVERIFIED_CONTEXT_CLASS=grok_general"
} > "${LUCY_ROOT}/state/last_outcome.env"

printf 'BEGIN_VALIDATED\nAugmented fallback (unverified answer):\nmock grok fallback\nEND_VALIDATED\n'
SH
chmod +x "${MOCK_ROOT}/lucy_chat.sh"

out="$({
  printf '/augmented fallback_only\n'
  printf 'grok path question\n'
  printf '/why\n'
  printf '/quit\n'
} | LUCY_RUNTIME_AUTHORITY_ROOT="${MOCK_ROOT}" "${LAUNCHER}" 2>&1)"

printf '%s\n' "${out}" | grep -q 'Outcome code: augmented_fallback_answer' || die "missing augmented fallback outcome"
printf '%s\n' "${out}" | grep -q 'Augmented provider: grok' || die "missing grok provider metadata in launcher output"
printf '%s\n' "${out}" | grep -q 'Trust class: unverified' || die "missing unverified trust class in launcher output"

ok "launcher surfaces grok provider metadata for augmented unverified outcomes"
echo "PASS: test_launcher_grok_provider_metadata_visibility"
