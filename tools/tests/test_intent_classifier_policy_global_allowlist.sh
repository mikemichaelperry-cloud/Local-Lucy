#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${LUCY_ROOT:-$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)}"
CLASSIFIER="${ROOT}/tools/router/classify_intent.py"

ok(){ echo "OK: $*"; }
die(){ echo "FAIL: $*" >&2; exit 1; }

[[ -x "${CLASSIFIER}" ]] || die "missing classifier: ${CLASSIFIER}"

query="Tell me, with evidence, what the most significant developments in global climate policy and AI safety have been in the past week; cite at least two authoritative news sources, describe how those developments interact, and explain the implications for technology regulation going forward."
out="$(python3 "${CLASSIFIER}" "${query}")"

allow_file="$(python3 - "${out}" <<'PY'
import json, sys
print((json.loads(sys.argv[1]).get("allow_domains_file") or "").strip())
PY
)"
intent_class="$(python3 - "${out}" <<'PY'
import json, sys
print((json.loads(sys.argv[1]).get("intent_class") or "").strip())
PY
)"
candidate_routes="$(python3 - "${out}" <<'PY'
import json, sys
print(",".join(json.loads(sys.argv[1]).get("candidate_routes") or []))
PY
)"

[[ "${allow_file}" == "config/trust/generated/policy_global_runtime.txt" ]] || die "unexpected allow_domains_file: ${allow_file}"
[[ "${intent_class}" == "current_fact" || "${intent_class}" == "evidence_check" ]] || die "unexpected intent_class: ${intent_class}"
printf '%s\n' "${candidate_routes}" | grep -Eq '(^|,)(NEWS|EVIDENCE)(,|$)' || die "unexpected candidate_routes: ${candidate_routes}"
ok "global policy current-fact query stays evidence-capable and uses policy-specific trust allowlist"

single_query="What are the latest climate policy developments this week?"
single_out="$(python3 "${CLASSIFIER}" "${single_query}")"
single_allow="$(python3 - "${single_out}" <<'PY'
import json, sys
print((json.loads(sys.argv[1]).get("allow_domains_file") or "").strip())
PY
)"
[[ "${single_allow}" == "config/trust/generated/policy_global_runtime.txt" ]] || die "single-domain policy query missed policy allowlist: ${single_allow}"
ok "single-domain recent policy query also uses policy-specific trust allowlist"

echo "PASS: test_intent_classifier_policy_global_allowlist"
