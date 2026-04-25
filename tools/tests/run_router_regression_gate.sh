#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROFILE="${1:-}"

if [[ "${PROFILE}" != "fast" && "${PROFILE}" != "full" ]]; then
  echo "usage: $0 <fast|full> [extra run_edge_prompt_sweep args...]" >&2
  exit 2
fi
shift || true

timestamp="$(date +%Y-%m-%dT%H-%M-%S%z)"
artifacts_dir="${ROOT}/tmp/router_regression_gate/${PROFILE}_${timestamp}"
report_prefix="LOCAL_LUCY_ROUTER_REGRESSION_GATE_${PROFILE^^}"

set +e
python3 "${ROOT}/tools/tests/run_edge_prompt_sweep.py" \
  --profile "${PROFILE}" \
  --fail-on-gate \
  --artifacts-dir "${artifacts_dir}" \
  --report-prefix "${report_prefix}" \
  "$@"
status=$?
set -e

summary_json="${artifacts_dir}/summary.json"
if [[ -f "${summary_json}" ]]; then
  python3 - "${summary_json}" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
data = json.loads(path.read_text(encoding="utf-8"))
print("Local Lucy router regression gate summary")
print(f"profile: {data['profile']}")
print(f"gate status: {data['gate_status']}")
print(f"prompts tested: {data['prompts_tested']}")
print(f"rule-consistent count: {data['rule_consistent_count']}")
print(f"provenance preserved count: {data['provenance_preserved_count']}")
print(f"anomalies: {data['anomalies']}")
print(f"authority-boundary violations: {data['authority_boundary_violations']}")
print(f"route mismatches: {data['route_mismatches']}")
print(f"manifest failures: {data['manifest_failures']}")
print(f"summary json: {path}")
print(f"report: {data['report_path']}")
PY
fi

exit "${status}"
