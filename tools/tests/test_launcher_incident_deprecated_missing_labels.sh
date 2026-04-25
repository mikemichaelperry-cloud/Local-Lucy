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
printf 'BEGIN_VALIDATED\nmock response\nEND_VALIDATED\n'
SH
chmod +x "${MOCK_ROOT}/lucy_chat.sh"

out="$({
  printf '/incident\n'
  printf '/quit\n'
} | LUCY_RUNTIME_AUTHORITY_ROOT="${MOCK_ROOT}" "${LAUNCHER}" 2>&1)"

printf '%s\n' "${out}" | grep -q 'last_route_metadata: not available' || die "expected not-available route metadata label"
printf '%s\n' "${out}" | grep -q 'last_outcome_metadata: not available' || die "expected not-available outcome metadata label"
printf '%s\n' "${out}" | grep -q 'last_route_file: missing' && die "deprecated missing route file label should not appear"
printf '%s\n' "${out}" | grep -q 'last_outcome_file: missing' && die "deprecated missing outcome file label should not appear"

ok "incident view uses not-available labels for deprecated missing file fields"
echo "PASS: test_launcher_incident_deprecated_missing_labels"
