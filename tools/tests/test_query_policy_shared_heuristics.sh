#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"
QPOL="${ROOT}/tools/query_policy.sh"

ok(){ echo "OK: $*"; }
die(){ echo "FAIL: $*" >&2; exit 1; }

[[ -x "${QPOL}" ]] || die "missing executable: ${QPOL}"

expect_yes() {
  local subcmd="$1"
  local q="$2"
  if ! "${QPOL}" "${subcmd}" "${q}" >/dev/null 2>&1; then
    die "expected yes for ${subcmd}: ${q}"
  fi
}

expect_no() {
  local subcmd="$1"
  local q="$2"
  if "${QPOL}" "${subcmd}" "${q}" >/dev/null 2>&1; then
    die "expected no for ${subcmd}: ${q}"
  fi
}

expect_yes is-memory-unsafe "Whats the latest Israel news?"
expect_yes is-memory-unsafe "Does tadalifil react with alcohol?"
expect_yes is-time-sensitive-or-web "search web for current weather"
expect_yes is-medical-high-risk "metformin side effects and alcohol"
expect_yes is-medical-high-risk "What are the side effects of ibuprofen?"
expect_yes is-medical-high-risk "Does tadalafil interact with alcohol?"
expect_yes is-medical-high-risk "What is Tadalifil?"
expect_yes is-medical-high-risk "What does amoxycillin do?"
expect_yes is-medical-high-risk "Is Lipitor safe with grapefruit?"
expect_yes is-medical-high-risk "Dose of Panadol?"
expect_yes is-medical-high-risk "What is the correct medication for high blood pressure?"
expect_yes is-medical-high-risk "my dog is vomiting and lethargic, what should i do?"
expect_yes is-medical-high-risk "is tinned tuna healthy for my dog oscar?"
expect_yes is-medical-high-risk "my dog oscar has runny poo"
expect_no is-memory-unsafe "what is lm317?"
expect_no is-medical-high-risk "what is lm317?"
expect_no is-medical-high-risk "what is grapefruit?"

ok "shared query policy detects unsafe/time-sensitive/medical patterns"
echo "PASS: test_query_policy_shared_heuristics"
