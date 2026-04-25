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

cp "${REAL_ROOT}/config/evidence_keys_allowlist.txt" "${FAKE_ROOT}/config/evidence_keys_allowlist.txt"
cp "${REAL_ROOT}/config/query_to_keys_v1.tsv" "${FAKE_ROOT}/config/query_to_keys_v1.tsv"

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
DOMAIN=bbc.com
TITLE: AI policy development
END_EVIDENCE_ITEM
====
BEGIN_EVIDENCE_ITEM
DOMAIN=gov.uk
TITLE: UK AI governance update
END_EVIDENCE_ITEM
====
EOF
printf 'bbc.com\ngov.uk\n' > "${out_dir}/domains.txt"
SH

cat > "${FAKE_ROOT}/tools/compose_from_evidence.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf 'Answer: AI governance and AI-safety policy work remains active. Sources: bbc.com gov.uk\n'
SH

cat > "${FAKE_ROOT}/tools/print_validated.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
cat
SH

cp "${REAL_ROOT}/tools/evidence_planner.py" "${FAKE_ROOT}/tools/evidence_planner.py"
cp "${REAL_ROOT}/tools/evidence_normalizer.py" "${FAKE_ROOT}/tools/evidence_normalizer.py"
chmod +x "${FAKE_ROOT}/tools/"*

run_positive_case(){
  local query="$1" out keys
  out="$(LUCY_ROOT="${FAKE_ROOT}" LUCY_ROUTER_BYPASS=1 LUCY_CHAT_FORCE_MODE=EVIDENCE "${LUCY_CHAT}" "${query}")"
  printf '%s\n' "${out}" | grep -qi 'AI governance and AI-safety policy work remains active' || die "missing synthesized AI-policy answer for query: ${query}"
  grep -Fxq "policy_ai_gov_1" "${FAKE_ROOT}/state/added_keys.log" || die "missing policy_ai_gov_1 key selection for query: ${query}"
  grep -Fxq "policy_ai_gov_2" "${FAKE_ROOT}/state/added_keys.log" || die "missing policy_ai_gov_2 key selection for query: ${query}"
  [[ "$(read_field EVIDENCE_NORMALIZER_MATCH_KIND)" == "mapping_phrase" ]] || die "expected mapping_phrase selection for query: ${query}"
  keys="$(read_field EVIDENCE_NORMALIZER_SELECTED_KEYS)"
  [[ "${keys}" == "policy_ai_gov_1,policy_ai_gov_2" ]] || die "unexpected selected keys for query: ${query} => ${keys}"
}

run_positive_case "What are the most significant developments in AI this past month?"
run_positive_case "What are the latest genai developments this past month?"
run_positive_case "What are the latest genai updates this past month?"
run_positive_case "What are the latest llm developments this past month?"
run_positive_case "What are the latest llm updates this past month?"
run_positive_case "What are the latest foundation model developments this past month?"
run_positive_case "What are the latest foundation model releases this past month?"
run_positive_case "What are the latest foundation models releases this past month?"
run_positive_case "What are the latest ai policy updates this past month?"
run_positive_case "What are the latest ai governance updates this past month?"
run_positive_case "What are the latest ai model releases this past month?"
run_positive_case "What are the latest model releases in ai this past month?"

negative_query="What are the latest developments in agriculture this past month?"
negative_out="$(LUCY_ROOT="${FAKE_ROOT}" LUCY_ROUTER_BYPASS=1 LUCY_CHAT_FORCE_MODE=EVIDENCE "${LUCY_CHAT}" "${negative_query}")"
printf '%s\n' "${negative_out}" | grep -qi 'Unable to answer from current evidence' || die "expected insufficient response for non-AI developments query"
[[ "$(read_field EVIDENCE_NORMALIZER_MATCH_KIND)" != "mapping_phrase" ]] || die "non-AI developments query unexpectedly matched mapping_phrase"
printf '%s\n' "$(read_field EVIDENCE_NORMALIZER_SELECTED_KEYS)" | grep -qi 'policy_ai_gov' && die "non-AI developments query unexpectedly selected policy_ai_gov keys"
ok "AI developments phrase families map to policy_ai_gov keys; non-AI developments does not inherit AI-policy mapping"

echo "PASS: test_lucy_chat_ai_developments_query_maps_policy_ai_keys"
