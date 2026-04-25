#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"
MANIFEST_CLEAN="${ROOT}/SHA256SUMS.clean"
MANIFEST_MIRROR="${ROOT}/SHA256SUMS"
COLLECTOR="${ROOT}/tools/sha_manifest.sh"

ok(){ echo "OK: $*"; }
die(){ echo "ERR: $*" >&2; exit 1; }

[[ -f "${MANIFEST_CLEAN}" ]] || die "missing manifest: ${MANIFEST_CLEAN}"
[[ -f "${MANIFEST_MIRROR}" ]] || die "missing manifest mirror: ${MANIFEST_MIRROR}"
ok "both SHA manifest files exist"

cmp -s "${MANIFEST_CLEAN}" "${MANIFEST_MIRROR}" || die "SHA manifest mirror drifted from SHA256SUMS.clean"
ok "SHA256SUMS mirror is byte-identical to SHA256SUMS.clean"

[[ -f "${COLLECTOR}" ]] || die "missing collector: ${COLLECTOR}"

assert_pattern() {
  local needle="$1"
  grep -Fq -- "${needle}" "${COLLECTOR}" || die "collector missing exclusion pattern: ${needle}"
  ok "collector excludes ${needle}"
}

assert_pattern '! -path "./tools/tmp/*"'
assert_pattern '! -path "./tools/tests/governor_migration/artifacts/*"'
assert_pattern '! -path "*/.venv/*"'
assert_pattern '! -path "*/.pytest_cache/*"'
assert_pattern '! -path "*/__pycache__/*"'
assert_pattern '! -name "*.pyc"'
assert_pattern '! -name "*.BROKEN.*"'
assert_pattern '! -name "*.fixbak.*"'

echo "PASS: test_sha_manifest_discipline"
