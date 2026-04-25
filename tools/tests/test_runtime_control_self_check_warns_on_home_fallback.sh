#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"
CONTROL_TOOL="${ROOT}/tools/runtime_control.py"

ok(){ echo "OK: $*"; }
die(){ echo "FAIL: $*" >&2; exit 1; }

[[ -f "${CONTROL_TOOL}" ]] || die "missing control tool: ${CONTROL_TOOL}"

TMPD="$(mktemp -d)"
trap 'rm -rf "${TMPD}"' EXIT
HOME_FALLBACK="${TMPD}/.codex-plus-home"
mkdir -p "${HOME_FALLBACK}"

self_check_json="$(
  env -i HOME="${HOME_FALLBACK}" PATH="${PATH}" PYTHONPATH="" \
    python3 "${CONTROL_TOOL}" self-check
)"

python3 - <<'PY' "${self_check_json}" "${HOME_FALLBACK}"
import json
import sys
from pathlib import Path

payload = json.loads(sys.argv[1])
home_value = Path(sys.argv[2])
expected_root = home_value / ".codex-api-home" / "lucy" / "runtime-v7"

assert payload["status"] == "warning"
assert payload["resolution_source"] == "home_fallback"
assert Path(payload["runtime_namespace_root"]) == expected_root
assert "runtime_namespace_home_fallback" in payload["warning_codes"]
assert any("HOME fallback only" in warning for warning in payload["warnings"])
assert payload["augmented_availability"]["status"] in {"unknown", "not_used", "disabled"}
PY

ok "runtime_control self-check warns loudly when runtime resolution is using HOME fallback only"
echo "PASS: test_runtime_control_self_check_warns_on_home_fallback"
