#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"
EXTRACTOR="${ROOT}/tools/router/extract_validated.py"

ok(){ echo "OK: $*"; }
die(){ echo "FAIL: $*" >&2; exit 1; }

[[ -x "${EXTRACTOR}" ]] || die "missing extractor: ${EXTRACTOR}"

sample="$(cat <<'EOF'
BEGIN_VALIDATED
Amoxicillin is a broad-spectrum antibiotic used to treat various bacterial infections.

Evidence:
type: entity
subject: Amoxicillin

Oscar is Mike’s dog. He has a fixation on cats; training approach uses leave-it, distance, and reward.

---- BEGIN PROPOSAL ----
[MEMORY PROPOSAL]
type: drug information
subject: Amoxicillin
summary: A broad-spectrum antibiotic used to treat various bacterial infections.
confidence: high
---- END PROPOSAL ----
END_VALIDATED
EOF
)"

parsed="$(printf '%s\n' "${sample}" | python3 "${EXTRACTOR}")"
answer="$(PARSED_JSON="${parsed}" python3 <<'PY'
import json, os
obj = json.loads(os.environ["PARSED_JSON"])
print(obj.get("answer", ""))
PY
)"

[[ "${answer}" == "Amoxicillin is a broad-spectrum antibiotic used to treat various bacterial infections." ]] \
  || die "unexpected extracted answer: ${answer}"

if printf '%s\n' "${answer}" | grep -Eqi 'oscar|memory proposal|drug information|type:|subject:|confidence:'; then
  die "extractor leaked proposal or memory noise into answer"
fi

ok "extract_validated stops before evidence/proposal leakage"

echo "PASS: test_extract_validated_proposal_noise"
