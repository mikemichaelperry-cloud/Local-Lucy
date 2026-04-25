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
printf 'backend exploded\n' >&2
exit 9
SH
chmod +x "${MOCK_ROOT}/lucy_chat.sh"

out="$({
  printf '/augmented direct_allowed\n'
  printf 'run augmented: broken request\n'
  printf '/why\n'
  printf '/quit\n'
} | LUCY_RUNTIME_AUTHORITY_ROOT="${MOCK_ROOT}" "${LAUNCHER}" 2>&1)"

printf '%s\n' "${out}" | grep -q '^Final mode: ERROR$' || die "backend failure should stay in ERROR mode"
printf '%s\n' "${out}" | grep -q '^Outcome code: execution_error$' || die "backend failure should synthesize execution_error"
printf '%s\n' "${out}" | grep -q '^Fallback used: false$' || die "backend failure must not mark fallback used"
printf '%s\n' "${out}" | grep -q '^Trust class: unknown$' || die "backend failure should keep trust unknown"
if printf '%s\n' "${out}" | grep -q 'augmented_fallback_answer\|augmented_answer'; then
  die "backend failure should not trigger augmented answer paths"
fi

ok "backend failure does not trigger augmented fallback even when augmentation is enabled"
echo "PASS: test_launcher_backend_failure_does_not_trigger_augmented_fallback"
