#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"
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
manifest_files="$(cut -d' ' -f3- "${MANIFEST_CLEAN}" | python3 -c 'import sys; [print(line.rstrip("\n").removeprefix("\\").removeprefix("./")) for line in sys.stdin]')"

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT
tracked_sorted="${tmpdir}/tracked.txt"
manifest_sorted="${tmpdir}/manifest.txt"
printf '%s\n' "${tracked_files}" | sort >"${tracked_sorted}"
printf '%s\n' "${manifest_files}" >"${manifest_sorted}"

if ! diff -q "${tracked_sorted}" "${manifest_sorted}" >/dev/null; then
    echo "FAIL: collector file list does not match manifest entries" >&2
    diff "${tracked_sorted}" "${manifest_sorted}" >&2 || true
    exit 1
fi
ok "collector file list matches manifest exactly"

printf '%s\n' "${tracked_files}" | grep -q '__pycache__' && die "__pycache__ should be excluded"
printf '%s\n' "${tracked_files}" | grep -q '\.venv/' && die ".venv should be excluded"
printf '%s\n' "${tracked_files}" | grep -q '^SHA256SUMS' && die "manifest files should not self-track"
ok "tracked scope excludes generated/runtime noise"

echo "PASS: test_sha_manifest_discipline"
