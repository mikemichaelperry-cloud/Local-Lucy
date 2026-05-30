#!/usr/bin/env bash
set -euo pipefail

# Test: Trusted evidence provider fetches live content for medical/vet queries.
# Requires: webclaw binary OR working fallback fetch gate.
# Safe to run offline — will gracefully fall back to domain-list responses.

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"

TRUSTED_PY="${ROOT}/tools/unverified_context_trusted.py"
WEB_EXTRACT_PY="${ROOT}/tools/internet/web_extract.py"
WEBCLAW_BIN="${ROOT}/bin/webclaw"

ok(){ echo "OK: $*"; }
die(){ echo "FAIL: $*" >&2; exit 1; }

[[ -f "${TRUSTED_PY}" ]] || die "missing ${TRUSTED_PY}"
[[ -f "${WEB_EXTRACT_PY}" ]] || die "missing ${WEB_EXTRACT_PY}"

export LUCY_ROOT="${ROOT}"

# ---------------------------------------------------------------------------
# 1. webclaw binary discoverable
# ---------------------------------------------------------------------------
if [[ -x "${WEBCLAW_BIN}" ]]; then
    ok "webclaw binary exists and is executable"
else
    ok "webclaw binary missing — fallback path will be used"
fi

# ---------------------------------------------------------------------------
# 2. web_extract adapter returns content for a known medical page
# ---------------------------------------------------------------------------
extract_result="$(python3 "${WEB_EXTRACT_PY}" "https://medlineplus.gov/appendicitis.html" --max-chars 1000 2>/dev/null || true)"
if [[ -n "${extract_result}" ]] && [[ "${#extract_result}" -gt 200 ]]; then
    ok "web_extract returns substantial text for MedlinePlus"
else
    die "web_extract returned empty or too short for MedlinePlus"
fi

# ---------------------------------------------------------------------------
# 3. Trusted provider returns bounded_response for medical query
# ---------------------------------------------------------------------------
# Use a query that matches medical keywords so _is_category_supported triggers
medical_json="$(python3 - "${TRUSTED_PY}" <<'PY'
import sys, os, json
os.environ["LUCY_ROOT"] = os.path.expanduser("~/lucy-v10")
sys.path.insert(0, os.path.join(os.environ["LUCY_ROOT"], "tools"))
import unverified_context_trusted as uct
result = uct.fetch_context("what is amoxicillin used for", evidence_reason="medical_context")
print(json.dumps(result))
PY
)"

[[ -n "${medical_json}" ]] || die "trusted provider returned empty for medical query"

medical_ok="$(python3 - "${medical_json}" <<'PY'
import json,sys
print("true" if json.loads(sys.argv[1]).get("ok") else "false")
PY
)"
medical_bounded="$(python3 - "${medical_json}" <<'PY'
import json,sys
print("true" if json.loads(sys.argv[1]).get("bounded_response") else "false")
PY
)"
medical_content="$(python3 - "${medical_json}" <<'PY'
import json,sys
print(json.loads(sys.argv[1]).get("content",""))
PY
)"

[[ "${medical_ok}" == "true" ]] || die "medical query: expected ok=true"
[[ "${medical_bounded}" == "true" ]] || die "medical query: expected bounded_response=true"
[[ "${#medical_content}" -gt 50 ]] || die "medical query: content too short"
ok "medical query returns bounded_response with content"

# ---------------------------------------------------------------------------
# 4. Trusted provider returns emergency guidance for vet query
# ---------------------------------------------------------------------------
vet_json="$(python3 "${TRUSTED_PY}" "my dog is vomiting" 2>/dev/null || true)"
[[ -n "${vet_json}" ]] || die "trusted provider returned empty for vet query"

vet_content="$(python3 - "${vet_json}" <<'PY'
import json,sys
print(json.loads(sys.argv[1]).get("content",""))
PY
)"

if echo "${vet_content}" | grep -qi "veterinary emergency"; then
    ok "vet emergency query includes emergency warning"
else
    die "vet emergency query missing emergency warning"
fi

# ---------------------------------------------------------------------------
# 5. Trusted provider falls back to domain list when search yields nothing
# ---------------------------------------------------------------------------
# Use a nonsense query that won't match any real article
nonsense_json="$(python3 - "${TRUSTED_PY}" <<'PY'
import sys, os, json
os.environ["LUCY_ROOT"] = os.path.expanduser("~/lucy-v10")
sys.path.insert(0, os.path.join(os.environ["LUCY_ROOT"], "tools"))
import unverified_context_trusted as uct
result = uct.fetch_context("xyzqwerty12345nonsense", evidence_reason="medical_context")
print(json.dumps(result))
PY
)"

[[ -n "${nonsense_json}" ]] || die "trusted provider returned empty for nonsense query"

nonsense_ok="$(python3 - "${nonsense_json}" <<'PY'
import json,sys
print("true" if json.loads(sys.argv[1]).get("ok") else "false")
PY
)"
nonsense_sources="$(python3 - "${nonsense_json}" <<'PY'
import json,sys
src=json.loads(sys.argv[1]).get("sources",[])
print("true" if len(src)>0 else "false")
PY
)"

[[ "${nonsense_ok}" == "true" ]] || die "nonsense query: expected ok=true (fallback)"
[[ "${nonsense_sources}" == "true" ]] || die "nonsense query: expected sources in fallback"
ok "nonsense query falls back to domain-list response"

# ---------------------------------------------------------------------------
# 6. web_extract graceful fallback when webclaw removed
# ---------------------------------------------------------------------------
if [[ -x "${WEBCLAW_BIN}" ]]; then
    mv "${WEBCLAW_BIN}" "${WEBCLAW_BIN}.testbak"
    fallback_result="$(python3 "${WEB_EXTRACT_PY}" "https://medlineplus.gov/appendicitis.html" --max-chars 1000 2>/dev/null || true)"
    mv "${WEBCLAW_BIN}.testbak" "${WEBCLAW_BIN}"
    if [[ -n "${fallback_result}" ]] && [[ "${#fallback_result}" -gt 200 ]]; then
        ok "web_extract fallback works when webclaw is absent"
    else
        die "web_extract fallback returned empty when webclaw absent"
    fi
else
    ok "webclaw absent — fallback already verified by test 2"
fi

echo ""
echo "PASS: test_trusted_evidence_live_fetch"
