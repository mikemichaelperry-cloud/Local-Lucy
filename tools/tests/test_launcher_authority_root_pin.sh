#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"
LAUNCHER="${ROOT}/tools/start_local_lucy_opt_experimental_v7_dev.sh"

ok(){ echo "OK: $*"; }
die(){ echo "FAIL: $*" >&2; exit 1; }

[[ -x "${LAUNCHER}" ]] || die "missing executable launcher: ${LAUNCHER}"

TMPD="$(mktemp -d)"
trap 'rm -rf "${TMPD}"' EXIT

set +e
out="$(printf '/quit\n' | LUCY_ROOT="${TMPD}" LUCY_LOCAL_PRELOAD_MODEL=0 LUCY_LOCAL_WORKER_ENABLED=0 timeout 20s "${LAUNCHER}" 2>&1)"
rc=$?
set -e

[[ "${rc}" -eq 0 ]] || die "launcher should ignore ambient LUCY_ROOT drift, rc=${rc}, out=${out}"
printf '%s' "${out}" | grep -q 'opt-experimental-v7-dev' || die "launcher banner should still identify the snapshot authority"

ok "launcher ignores ambient LUCY_ROOT and stays pinned to the snapshot by default"
echo "PASS: test_launcher_authority_root_pin"
