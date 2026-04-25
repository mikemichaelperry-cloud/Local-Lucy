#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DEFAULT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"
ROOT="${LUCY_ROOT:-$ROOT_DEFAULT}"
CFG="$ROOT/config"
TOOLS="$ROOT/tools/internet"
EVID="$ROOT/evidence"

PROD_MAP="$CFG/url_map.yaml"
TEST_MAP="$CFG/url_map_tests.yaml"
TRUSTED="$CFG/trusted_domains.yaml"
POLICY="$CFG/evidence_policy.yaml"

TEST_TRUSTED="$CFG/trusted_domains_tests.yaml"
TEST_MAP_TMP="$CFG/url_map_tests_tmp.yaml"

pass(){ echo "PASS: $*"; }
fail(){ echo "FAIL: $*" >&2; exit 1; }

need(){ [[ -f "$1" ]] || fail "missing file: $1"; }

need "$PROD_MAP"
need "$TEST_MAP"
need "$TRUSTED"
need "$POLICY"
need "$TOOLS/fetch_evidence.sh"
need "$TOOLS/fetch_evidence_test.sh"
need "$TOOLS/fetch_url.py"

echo "== Local Lucy Internet Limit Test =="
echo "time: $(date -Is)"
echo

echo "-- Smoke: prod key RFC_7231 (should be cached or fetched)"
if out="$("$TOOLS/fetch_evidence.sh" RFC_7231)"; then
  echo "$out"
  echo "$out" | grep -q '"key": "RFC_7231"' || fail "prod smoke missing key"
  pass "prod smoke RFC_7231"
else
  fail "prod smoke RFC_7231 failed"
fi
echo

echo "-- Adversarial: BAD_LOCALHOST_TEST (expect localhost forbidden)"
if out="$("$TOOLS/fetch_evidence_test.sh" BAD_LOCALHOST_TEST 2>&1)"; then
  fail "BAD_LOCALHOST_TEST unexpectedly succeeded"
else
  echo "$out"
  echo "$out" | grep -q "localhost forbidden" || fail "BAD_LOCALHOST_TEST wrong error"
  pass "BAD_LOCALHOST_TEST rejected correctly"
fi
echo

echo "-- Adversarial: BAD_DOMAIN_MISMATCH (expect declared domain mismatch)"
if out="$("$TOOLS/fetch_evidence_test.sh" BAD_DOMAIN_MISMATCH 2>&1)"; then
  fail "BAD_DOMAIN_MISMATCH unexpectedly succeeded"
else
  echo "$out"
  echo "$out" | grep -q "url host does not match declared domain" || fail "BAD_DOMAIN_MISMATCH wrong error"
  pass "BAD_DOMAIN_MISMATCH rejected correctly"
fi
echo

echo "-- Redirect chain test (test-only config; no prod pollution)"
# Create test-only trusted domains by copying prod and adding httpbin.org
cp -f "$TRUSTED" "$TEST_TRUSTED"
ROOT="$ROOT" python3 - <<'PY'
import os
from pathlib import Path
p = Path(os.environ["ROOT"])/"config/trusted_domains_tests.yaml"
t = p.read_text()
if "- httpbin.org" not in t:
    t = t.replace("exact:\n", "exact:\n  - httpbin.org\n")
p.write_text(t)
print("prepared trusted_domains_tests.yaml")
PY

# Create a tmp test url map containing the existing tests + a redirect key
cp -f "$TEST_MAP" "$TEST_MAP_TMP"
ROOT="$ROOT" python3 - <<'PY'
import os
from pathlib import Path
p = Path(os.environ["ROOT"])/"config/url_map_tests_tmp.yaml"
s = p.read_text()
if "REDIRECT_2" not in s:
    s = s.replace("urls:\n", "urls:\n  REDIRECT_2:\n    url: https://httpbin.org/redirect/2\n    domain: httpbin.org\n    tags: [test]\n\n")
p.write_text(s)
print("prepared url_map_tests_tmp.yaml")
PY

# Run redirect fetch via fetch_url.py directly (so we can point at tmp configs)
if out="$(python3 "$TOOLS/fetch_url.py" \
  --key REDIRECT_2 \
  --url-map "$TEST_MAP_TMP" \
  --trusted "$TEST_TRUSTED" \
  --policy "$POLICY" \
  --out "$EVID" 2>&1)"; then
  echo "$out"
  echo "$out" | grep -q '"key": "REDIRECT_2"' || fail "redirect fetch missing key"
  pass "redirect chain REDIRECT_2"
else
  echo "$out"
  fail "redirect chain REDIRECT_2 failed"
fi

# Validate meta final_url stayed on allowlisted domain
META="$EVID/cache/by_url/REDIRECT_2/meta.json"
if [[ -f "$META" ]]; then
  ROOT="$ROOT" python3 - <<'PY'
import json
import os
import pathlib
m = json.loads((pathlib.Path(os.environ["ROOT"])/"evidence/cache/by_url/REDIRECT_2/meta.json").read_text())
assert m["domain"] == "httpbin.org"
assert m["final_url"].startswith("https://httpbin.org/")
print("meta ok:", m["final_url"])
PY
  pass "redirect meta validated"
else
  fail "redirect meta missing"
fi

# Cleanup test-only config files and redirect cache
rm -f "$TEST_TRUSTED" "$TEST_MAP_TMP"
rm -rf "$EVID/cache/by_url/REDIRECT_2" || true

echo
pass "ALL LIMIT TESTS PASSED"
