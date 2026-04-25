#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"
INSPECTOR="${ROOT}/tools/diag/print_runtime_authority_chain.py"

ok(){ echo "OK: $*"; }
die(){ echo "FAIL: $*" >&2; exit 1; }

[[ -f "${INSPECTOR}" ]] || die "missing authority inspector: ${INSPECTOR}"

payload="$(python3 "${INSPECTOR}" --json)"

python3 - <<'PY' "${payload}" "${ROOT}"
import json
import sys
from pathlib import Path

payload = json.loads(sys.argv[1])
root = Path(sys.argv[2]).resolve()

assert Path(payload["snapshot_root"]) == root
assert Path(payload["active_root"]) == root
assert Path(payload["launcher"]) == root / "tools" / "start_local_lucy_opt_experimental_v7_dev.sh"
assert Path(payload["desktop_manifest"]) == root / "config" / "launcher" / "desktop_launchers.tsv"
assert Path(payload["desktop_current_exec_target"]) == root / "tools" / "start_local_lucy_opt_experimental_v7_dev.sh"
assert payload["desktop_current_status"] == "aligned"
assert payload["runtime_bridge_classification"] == "permitted_global_control_plane_exception"
assert Path(payload["runtime_request"]) == root / "tools" / "runtime_request.py"
assert Path(payload["runtime_request_root"]) == root
assert Path(payload["runtime_namespace_root"]) == Path("/home/mike/.codex-api-home/lucy/runtime-v7")
assert Path(payload["legacy_runtime_namespace_root"]) == Path("/home/mike/lucy/runtime-v7")
assert payload["legacy_runtime_namespace_present"] in {"true", "false"}
assert payload["legacy_runtime_namespace_status"] in {"absent", "same", "stale_parallel_tree_present"}
assert Path(payload["lucy_chat"]) == root / "lucy_chat.sh"
assert Path(payload["manifest_source"]) == root / "tools" / "router" / "core" / "route_manifest.py"
assert payload["runtime_bridge_status"] == "aligned"
PY

ok "authority inspector reports aligned launcher, bridge, request, and manifest paths"

OVERRIDE_ROOT="$(mktemp -d)"
trap 'rm -rf "${OVERRIDE_ROOT}"' EXIT
override_payload="$(LUCY_RUNTIME_AUTHORITY_ROOT="${OVERRIDE_ROOT}" python3 "${INSPECTOR}" --json)"

python3 - <<'PY' "${override_payload}" "${OVERRIDE_ROOT}"
import json
import sys
from pathlib import Path

payload = json.loads(sys.argv[1])
override = Path(sys.argv[2]).resolve()

assert Path(payload["runtime_request_root"]) == override
assert Path(payload["active_root"]) == override
assert Path(payload["runtime_request"]) == override / "tools" / "runtime_request.py"
assert Path(payload["runtime_bridge_request_tool"]) == override / "tools" / "runtime_request.py"
assert payload["runtime_bridge_status"] == "aligned"
PY

ok "authority inspector reflects explicit bridge/request override roots"
echo "PASS: test_runtime_authority_chain_inspection"
