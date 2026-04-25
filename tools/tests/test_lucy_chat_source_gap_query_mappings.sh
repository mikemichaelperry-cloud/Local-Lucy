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
DOMAIN=reuters.com
TITLE: Stub Reuters item
END_EVIDENCE_ITEM
====
BEGIN_EVIDENCE_ITEM
DOMAIN=bbc.com
TITLE: Stub BBC item
END_EVIDENCE_ITEM
====
EOF
printf 'reuters.com\nbbc.com\n' > "${out_dir}/domains.txt"
SH

cat > "${FAKE_ROOT}/tools/compose_from_evidence.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf 'Answer: stub evidence answer. Sources: reuters.com bbc.com\n'
SH

cat > "${FAKE_ROOT}/tools/print_validated.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
cat
SH

cp "${REAL_ROOT}/tools/evidence_planner.py" "${FAKE_ROOT}/tools/evidence_planner.py"
cp "${REAL_ROOT}/tools/evidence_normalizer.py" "${FAKE_ROOT}/tools/evidence_normalizer.py"
chmod +x "${FAKE_ROOT}/tools/"*

run_case(){
  local query="$1" expected_keys_csv="$2"
  local out keys
  out="$(LUCY_ROOT="${FAKE_ROOT}" LUCY_ROUTER_BYPASS=1 LUCY_CHAT_FORCE_MODE=EVIDENCE "${LUCY_CHAT}" "${query}")"
  printf '%s\n' "${out}" | grep -qi 'stub evidence answer' || die "missing stub answer for query: ${query}"
  [[ "$(read_field EVIDENCE_NORMALIZER_MATCH_KIND)" == "mapping_phrase" ]] || die "expected mapping_phrase for query: ${query}"
  keys="$(read_field EVIDENCE_NORMALIZER_SELECTED_KEYS)"
  [[ "${keys}" == "${expected_keys_csv}" ]] || die "unexpected keys for query: ${query} => ${keys}"
}

run_case "What is the latest U.S. CPI inflation rate and release date? cite sources." "cpi_us_1,cpi_us_2"
grep -Fxq "cpi_us_1" "${FAKE_ROOT}/state/added_keys.log" || die "missing cpi_us_1 selection"
grep -Fxq "cpi_us_2" "${FAKE_ROOT}/state/added_keys.log" || die "missing cpi_us_2 selection"

run_case "Is it safe to travel to Lebanon right now? cite official advisories." "travel_lebanon_1,travel_lebanon_2"
grep -Fxq "travel_lebanon_1" "${FAKE_ROOT}/state/added_keys.log" || die "missing travel_lebanon_1 selection"
grep -Fxq "travel_lebanon_2" "${FAKE_ROOT}/state/added_keys.log" || die "missing travel_lebanon_2 selection"

run_case "What recent statements were made by major labs about model evaluations?" "ai_labs_evals_1,ai_labs_evals_2"
grep -Fxq "ai_labs_evals_1" "${FAKE_ROOT}/state/added_keys.log" || die "missing ai_labs_evals_1 selection"
grep -Fxq "ai_labs_evals_2" "${FAKE_ROOT}/state/added_keys.log" || die "missing ai_labs_evals_2 selection"

run_case "What are the latest ai policy updates this past month?" "policy_ai_gov_1,policy_ai_gov_2"
grep -Fxq "policy_ai_gov_1" "${FAKE_ROOT}/state/added_keys.log" || die "missing policy_ai_gov_1 selection"
grep -Fxq "policy_ai_gov_2" "${FAKE_ROOT}/state/added_keys.log" || die "missing policy_ai_gov_2 selection"

negative_query="What are the latest developments in agriculture this past month?"
negative_out="$(LUCY_ROOT="${FAKE_ROOT}" LUCY_ROUTER_BYPASS=1 LUCY_CHAT_FORCE_MODE=EVIDENCE "${LUCY_CHAT}" "${negative_query}")"
printf '%s\n' "${negative_out}" | grep -qi 'Unable to answer from current evidence' || die "expected insufficient response for guard query"
printf '%s\n' "$(read_field EVIDENCE_NORMALIZER_SELECTED_KEYS)" | grep -Eqi '(cpi_us_|travel_lebanon_)' \
  && die "guard query unexpectedly selected new source-gap closure keys"
ok "source-gap phrase families map deterministically without dragging unrelated developments prompts"

echo "PASS: test_lucy_chat_source_gap_query_mappings"
