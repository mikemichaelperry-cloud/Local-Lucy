#!/usr/bin/env bash
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
VALIDATOR="${ROOT}/tools/internet/validate_answer.py"
TMPDIR_TEST="$(mktemp -d)"
trap 'rm -rf "${TMPDIR_TEST}"' EXIT

mkdir -p "${TMPDIR_TEST}/cache/by_url/test"
cat > "${TMPDIR_TEST}/cache/by_url/test/meta.json" <<'EOF'
{"sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","domain":"bbc.com"}
EOF

good_text=$'Summary: Based on current trusted sources, climate-policy and AI-governance activity both appear active this week, but the overlap remains bounded rather than exhaustive.\n\nKey points:\n- Current trusted sources indicate live movement in both domains.\n\nLimits: This is a bounded current-source answer, not a complete survey.\nSources: bbc.com, gov.uk, ec.europa.eu'

LUCY_POLICY_VALIDATION_PROFILE=policy_global_recent \
LUCY_POLICY_VALIDATION_ALLOW_BOUNDED=1 \
LUCY_POLICY_VALIDATION_SHAPE=compound_climate_ai \
LUCY_POLICY_VALIDATION_UNIQUE_DOMAINS=4 \
python3 "${VALIDATOR}" --mode single --evidence-root "${TMPDIR_TEST}" <<< "${good_text}" >/dev/null \
  || { echo "FAIL: bounded policy validation should pass" >&2; exit 1; }

bad_text=$'Summary: This is definitely the complete picture.\nSources: bbc.com, gov.uk'
if LUCY_POLICY_VALIDATION_PROFILE=policy_global_recent \
  LUCY_POLICY_VALIDATION_ALLOW_BOUNDED=1 \
  LUCY_POLICY_VALIDATION_SHAPE=single_ai \
  LUCY_POLICY_VALIDATION_UNIQUE_DOMAINS=2 \
  python3 "${VALIDATOR}" --mode single --evidence-root "${TMPDIR_TEST}" <<< "${bad_text}" >/dev/null 2>&1; then
  echo "FAIL: overconfident policy validation should fail" >&2
  exit 1
fi

echo "PASS: validate_answer policy_global bounded mode"
