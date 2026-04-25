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
echo "ERROR: no evidence items fetched" >&2
exit 2
SH

cat > "${FAKE_ROOT}/tools/compose_from_evidence.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf 'Answer: should not be used\n'
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

printf '%s\n' "${out}" | grep -q 'Insufficient trusted evidence across requested climate-policy and AI-governance domains.' || die "missing bounded insufficiency summary"
printf '%s\n' "${out}" | grep -q 'query is broad and cross-domain; ask climate policy only, AI safety only, or one named regulator, region, or decision.' || die "missing bounded retry guidance"
[[ "$(read_field ACTION_HINT)" == "query is broad and cross-domain; ask climate policy only, AI safety only, or one named regulator, region, or decision" ]] || die "unexpected ACTION_HINT"
ok "compound policy insufficiency response is bounded and /why-ready via ACTION_HINT"

echo "PASS: test_lucy_chat_compound_policy_insufficient_hint"
