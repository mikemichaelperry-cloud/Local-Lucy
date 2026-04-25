#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"
CLASSIFIER="${ROOT}/tools/router/classify_intent.py"

ok(){ echo "OK: $*"; }
die(){ echo "FAIL: $*" >&2; exit 1; }

[[ -x "${CLASSIFIER}" ]] || die "missing classifier: ${CLASSIFIER}"

assert_medical_case() {
  local query="$1"
  local expected_candidate="$2"
  local plan
  plan="$("${CLASSIFIER}" "${query}")"
  python3 - "${plan}" "${query}" "${expected_candidate}" <<'PY'
import json
import sys

plan = json.loads(sys.argv[1])
expected_query = sys.argv[2]
expected_candidate = sys.argv[3]
detector = plan.get("medical_detector") or {}
if plan.get("intent") != "MEDICAL_INFO":
    raise SystemExit(f"expected MEDICAL_INFO for {expected_query!r}, got {plan.get('intent')!r}")
if detector.get("detector_fired") is not True:
    raise SystemExit(f"medical detector did not fire for {expected_query!r}")
if detector.get("normalized_candidate") != expected_candidate:
    raise SystemExit(
        f"unexpected normalized_candidate for {expected_query!r}: {detector.get('normalized_candidate')!r}"
    )
if detector.get("confidence") not in {"high", "medium"}:
    raise SystemExit(f"unexpected detector confidence for {expected_query!r}: {detector.get('confidence')!r}")
PY
}

assert_local_case() {
  local query="$1"
  local plan
  plan="$("${CLASSIFIER}" "${query}")"
  python3 - "${plan}" "${query}" <<'PY'
import json
import sys

plan = json.loads(sys.argv[1])
expected_query = sys.argv[2]
detector = plan.get("medical_detector") or {}
if plan.get("intent") == "MEDICAL_INFO":
    raise SystemExit(f"unexpected MEDICAL_INFO for {expected_query!r}")
if detector.get("detector_fired") is True:
    raise SystemExit(f"medical detector should not fire for {expected_query!r}")
for field in ("candidate_medication", "normalized_candidate", "normalized_query", "pattern_family"):
    if detector.get(field) not in {"", None}:
        raise SystemExit(f"expected blank {field} for non-fired detector on {expected_query!r}, got {detector.get(field)!r}")
PY
}

assert_medical_case "What are the side effects of ibuprofen?" "ibuprofen"
assert_medical_case "Does tadalafil interact with alcohol?" "tadalafil"
assert_medical_case "What is Tadalifil?" "tadalafil"
assert_medical_case "What does amoxycillin do?" "amoxicillin"
assert_medical_case "Is Lipitor safe with grapefruit?" "atorvastatin"
assert_medical_case "Dose of Panadol?" "paracetamol"
assert_medical_case "What about Aspirin for blood pressure?" "aspirin"
assert_medical_case "What is aspirin?" "aspirin"
assert_medical_case "What is lisinopril?" "lisinopril"
assert_local_case "What is grapefruit?"

ok "broader medication detector catches common medication phrasing and stays conservative on non-medical prompts"
echo "PASS: test_medication_detector_broader_coverage"
