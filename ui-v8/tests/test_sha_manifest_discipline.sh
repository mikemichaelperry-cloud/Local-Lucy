#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)"
MANIFEST_CLEAN="${ROOT}/SHA256SUMS.clean"
MANIFEST_MIRROR="${ROOT}/SHA256SUMS"
COLLECTOR="${ROOT}/tools/sha_manifest.sh"

ok(){ echo "OK: $*"; }
die(){ echo "FAIL: $*" >&2; exit 1; }

[[ -f "${MANIFEST_CLEAN}" ]] || die "missing manifest: ${MANIFEST_CLEAN}"
[[ -f "${MANIFEST_MIRROR}" ]] || die "missing manifest mirror: ${MANIFEST_MIRROR}"
[[ -x "${COLLECTOR}" ]] || die "missing collector: ${COLLECTOR}"

cmp -s "${MANIFEST_CLEAN}" "${MANIFEST_MIRROR}" || die "SHA manifest mirror drifted from SHA256SUMS.clean"
ok "SHA256SUMS mirror is byte-identical to SHA256SUMS.clean"

"${COLLECTOR}" check >/dev/null
ok "sha manifest check passes"

tracked_files="$("${COLLECTOR}" list)"

printf '%s\n' "${tracked_files}" | grep -qx 'app/main.py' || die "expected app/main.py in tracked scope"
printf '%s\n' "${tracked_files}" | grep -qx 'tests/test_voice_ptt_offscreen.py' || die "expected UI tests in tracked scope"
printf '%s\n' "${tracked_files}" | grep -qx 'tools/sha_manifest.sh' || die "expected collector to self-track"
printf '%s\n' "${tracked_files}" | grep -q '^SHA256SUMS' && die "manifest files should not self-track"
printf '%s\n' "${tracked_files}" | grep -q '__pycache__' && die "__pycache__ should be excluded"
printf '%s\n' "${tracked_files}" | grep -q '\.venv/' && die ".venv should be excluded"
ok "tracked scope includes source/tests and excludes generated/runtime noise"

echo "PASS: test_sha_manifest_discipline"
