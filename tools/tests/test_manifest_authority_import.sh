#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"
PLAN_TO_PIPELINE="${ROOT}/tools/router/plan_to_pipeline.py"
EXPECTED_MANIFEST="${ROOT}/tools/router/core/route_manifest.py"

ok(){ echo "OK: $*"; }
die(){ echo "FAIL: $*" >&2; exit 1; }

[[ -f "${PLAN_TO_PIPELINE}" ]] || die "missing plan_to_pipeline: ${PLAN_TO_PIPELINE}"
[[ -f "${EXPECTED_MANIFEST}" ]] || die "missing manifest source: ${EXPECTED_MANIFEST}"

python3 - <<'PY' "${PLAN_TO_PIPELINE}" "${EXPECTED_MANIFEST}" "${ROOT}"
import importlib.util
import os
import sys
from pathlib import Path

plan_path = Path(sys.argv[1]).resolve()
expected_manifest = Path(sys.argv[2]).resolve()
expected_root = Path(sys.argv[3]).resolve()
sys.path.insert(0, str(plan_path.parent))
spec = importlib.util.spec_from_file_location("plan_to_pipeline_under_test", plan_path)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
route_manifest = sys.modules["route_manifest"]
assert Path(route_manifest.__file__).resolve() == expected_manifest

override_root = expected_root.parent / "tmp" / "plan_to_pipeline_override_check"
override_root.mkdir(parents=True, exist_ok=True)
os.environ.pop("LUCY_RUNTIME_AUTHORITY_ROOT", None)
os.environ["LUCY_ROOT"] = str(override_root)
assert Path(module._root_dir()).resolve() == expected_root
os.environ["LUCY_RUNTIME_AUTHORITY_ROOT"] = str(override_root)
assert Path(module._root_dir()).resolve() == override_root.resolve()
PY

ok "plan_to_pipeline imports the snapshot-local route_manifest source and only honors explicit authority override"
echo "PASS: test_manifest_authority_import"
