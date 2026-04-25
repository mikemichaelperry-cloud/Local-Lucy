#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REAL_ROOT="${LUCY_ROOT:-$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)}"
LUCY_CHAT="${REAL_ROOT}/lucy_chat.sh"

ok(){ echo "OK: $*"; }
die(){ echo "FAIL: $*" >&2; exit 1; }
read_field(){ awk -F= -v k="$1" '$1==k {print $2; exit}' "${FAKE_ROOT}/state/last_outcome.env"; }

[[ -x "${LUCY_CHAT}" ]] || die "missing executable: ${LUCY_CHAT}"

TMPD="$(mktemp -d)"
trap 'rm -rf "${TMPD}"' EXIT
FAKE_ROOT="${TMPD}/root"
mkdir -p "${FAKE_ROOT}/tools" "${FAKE_ROOT}/config" "${FAKE_ROOT}/state" "${FAKE_ROOT}/evidence" "${FAKE_ROOT}/cache/evidence"

cat > "${FAKE_ROOT}/config/evidence_keys_allowlist.txt" <<'EOF'
policy_climate_1
policy_climate_2
policy_ai_gov_1
policy_ai_gov_2
policy_regulation_1
policy_regulation_2
EOF

cat > "${FAKE_ROOT}/config/query_to_keys_v1.tsv" <<'EOF'
recent global climate policy developments in past week	EVIDENCE	policy_climate_1 policy_climate_2
recent ai safety and ai regulation developments in past week	EVIDENCE	policy_ai_gov_1 policy_ai_gov_2
technology regulation implications across climate policy and ai safety	EVIDENCE	policy_regulation_1 policy_regulation_2
climate policy	EVIDENCE	policy_climate_1 policy_climate_2
ai safety	EVIDENCE	policy_ai_gov_1 policy_ai_gov_2
technology regulation	EVIDENCE	policy_regulation_1 policy_regulation_2
EOF

cat > "${FAKE_ROOT}/tools/evidence_session.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
state_dir="${LUCY_ROOT}/state"
mkdir -p "${state_dir}"
case "${1:-}" in
  clear)
    : > "${state_dir}/added_keys.log"
    ;;
  add)
    shift
    printf '%s\n' "$@" >> "${state_dir}/added_keys.log"
    ;;
  list)
    ;;
esac
SH

cat > "${FAKE_ROOT}/tools/build_evidence_pack.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
out_dir="${1:?outdir}"
mkdir -p "${out_dir}"
cat > "${out_dir}/evidence_pack.txt" <<'EOF'
BEGIN_EVIDENCE_ITEM
DOMAIN=apnews.com
TITLE: Climate policy package
END_EVIDENCE_ITEM
====
BEGIN_EVIDENCE_ITEM
DOMAIN=reuters.com
TITLE: AI governance package
END_EVIDENCE_ITEM
====
BEGIN_EVIDENCE_ITEM
DOMAIN=ec.europa.eu
TITLE: Technology regulation package
END_EVIDENCE_ITEM
====
EOF
printf 'apnews.com\nreuters.com\nec.europa.eu\n' > "${out_dir}/domains.txt"
SH

cat > "${FAKE_ROOT}/tools/compose_from_evidence.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf 'Answer: Climate and AI governance developments now point to tighter technology regulation. Sources: apnews.com reuters.com ec.europa.eu\n'
SH

cat > "${FAKE_ROOT}/tools/print_validated.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
cat
SH

cp "${REAL_ROOT}/tools/evidence_planner.py" "${FAKE_ROOT}/tools/evidence_planner.py"
cp "${REAL_ROOT}/tools/evidence_normalizer.py" "${FAKE_ROOT}/tools/evidence_normalizer.py"
chmod +x "${FAKE_ROOT}/tools/"*

query="Tell me, with evidence, what the most significant developments in global climate policy and AI safety have been in the past week; cite at least two authoritative news sources, describe how those developments interact, and explain the implications for technology regulation going forward."
out="$(LUCY_ROOT="${FAKE_ROOT}" LUCY_ROUTER_BYPASS=1 LUCY_CHAT_FORCE_MODE=EVIDENCE "${LUCY_CHAT}" "${query}")"

printf '%s\n' "${out}" | grep -q 'Climate and AI governance developments now point to tighter technology regulation' || die "missing synthesized answer"
grep -Fxq "policy_climate_1" "${FAKE_ROOT}/state/added_keys.log" || die "missing climate key"
grep -Fxq "policy_ai_gov_1" "${FAKE_ROOT}/state/added_keys.log" || die "missing ai key"
grep -Fxq "policy_regulation_1" "${FAKE_ROOT}/state/added_keys.log" || die "missing regulation key"
[[ "$(read_field EVIDENCE_PLANNER_SELECTED_ADAPTER)" == "compound_policy" ]] || die "expected compound_policy planner adapter"
[[ "$(read_field EVIDENCE_NORMALIZER_MATCH_KIND)" == "planner_compound_policy" ]] || die "expected compound policy key selection trace"
ok "compound policy evidence query aggregates bounded policy subqueries into one conservative evidence run"

echo "PASS: test_lucy_chat_compound_policy_query_success"
