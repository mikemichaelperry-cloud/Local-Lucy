#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${LUCY_ROOT:-$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)}"
PLANNER="${ROOT}/tools/evidence_planner.py"

ok(){ echo "OK: $*"; }
die(){ echo "FAIL: $*" >&2; exit 1; }

[[ -x "${PLANNER}" ]] || die "missing planner: ${PLANNER}"

query="Tell me, with evidence, what the most significant developments in global climate policy and AI safety have been in the past week; cite at least two authoritative news sources, describe how those developments interact, and explain the implications for technology regulation going forward."
out="$(python3 "${PLANNER}" --mode EVIDENCE --query "${query}")"

printf '%s\n' "${out}" | grep -q '"adapter": "compound_policy"' || die "expected compound_policy adapter"
printf '%s\n' "${out}" | grep -q 'recent global climate policy developments in past week' || die "missing climate subquery"
printf '%s\n' "${out}" | grep -q 'recent ai safety and ai regulation developments in past week' || die "missing ai subquery"
printf '%s\n' "${out}" | grep -q 'technology regulation implications across climate policy and ai safety' || die "missing overlap subquery"
ok "compound policy query is decomposed into deterministic retrieval subqueries"

echo "PASS: test_evidence_planner_compound_policy_query"
