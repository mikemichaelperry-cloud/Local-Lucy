#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"
REQUEST_TOOL="${ROOT}/tools/runtime_request.py"

ok(){ echo "OK: $*"; }
die(){ echo "FAIL: $*" >&2; exit 1; }

[[ -f "${REQUEST_TOOL}" ]] || die "missing request tool: ${REQUEST_TOOL}"

TMPD="$(mktemp -d)"
trap 'rm -rf "${TMPD}"' EXIT
OVERRIDE_ROOT="${TMPD}/override_root"
mkdir -p "${OVERRIDE_ROOT}/state" "${OVERRIDE_ROOT}/tools/router/core"
touch "${OVERRIDE_ROOT}/lucy_chat.sh"

python3 - <<'PY' "${REQUEST_TOOL}" "${ROOT}" "${OVERRIDE_ROOT}"
import os
import sys
from pathlib import Path

tool_path = Path(sys.argv[1])
expected_root = Path(sys.argv[2]).resolve()
override_root = Path(sys.argv[3]).resolve()

sys.path.insert(0, str(tool_path.parent))
import runtime_request as module

os.environ.pop("LUCY_RUNTIME_AUTHORITY_ROOT", None)
os.environ["LUCY_ROOT"] = str(override_root)
assert module.resolve_root() == expected_root
assert module.resolve_paths().chat_bin == expected_root / "lucy_chat.sh"

os.environ["LUCY_RUNTIME_AUTHORITY_ROOT"] = str(override_root)
assert module.resolve_root() == override_root
assert module.resolve_paths().chat_bin == override_root / "lucy_chat.sh"
PY

ok "runtime_request defaults to snapshot-local authority and only honors explicit override"
echo "PASS: test_runtime_request_authority_resolution"
