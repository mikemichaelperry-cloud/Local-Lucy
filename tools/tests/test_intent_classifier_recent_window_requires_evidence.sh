#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${LUCY_ROOT:-$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)}"
CLASSIFIER="${ROOT}/tools/router/classify_intent.py"

ok(){ echo "OK: $*"; }
die(){ echo "FAIL: $*" >&2; exit 1; }

[[ -x "${CLASSIFIER}" ]] || die "missing classifier: ${CLASSIFIER}"

query="What are the most significant developments in AI this past month?"
out="$(python3 "${CLASSIFIER}" "${query}")"

intent_class="$(python3 - "${out}" <<'PY'
import json, sys
print((json.loads(sys.argv[1]).get("intent_class") or "").strip())
PY
)"
temporal_flag="$(python3 - "${out}" <<'PY'
import json, sys
payload=json.loads(sys.argv[1])
print("1" if bool((payload.get("routing_signals") or {}).get("temporal")) else "0")
PY
)"
candidate_routes="$(python3 - "${out}" <<'PY'
import json, sys
print(",".join(json.loads(sys.argv[1]).get("candidate_routes") or []))
PY
)"

[[ "${intent_class}" == "current_fact" ]] || die "expected current_fact intent_class, got: ${intent_class}"
[[ "${temporal_flag}" == "1" ]] || die "expected routing_signals.temporal=1"
printf '%s\n' "${candidate_routes}" | grep -Eq '(^|,)(NEWS|EVIDENCE)(,|$)' || die "expected NEWS/EVIDENCE candidate routes, got: ${candidate_routes}"
ok "recent-window phrasing ('past month') is classified as current-fact evidence/news routing"

echo "PASS: test_intent_classifier_recent_window_requires_evidence"
