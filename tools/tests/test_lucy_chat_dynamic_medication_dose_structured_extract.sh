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
mkdir -p \
  "${FAKE_ROOT}/tools/router/core" \
  "${FAKE_ROOT}/config/trust/generated" \
  "${FAKE_ROOT}/state" \
  "${FAKE_ROOT}/evidence" \
  "${FAKE_ROOT}/cache/evidence"

: > "${FAKE_ROOT}/config/evidence_keys_allowlist.txt"
: > "${FAKE_ROOT}/config/query_to_keys_v1.tsv"
: > "${FAKE_ROOT}/config/evidence_keymap_v1.tsv"
cp "${REAL_ROOT}/config/evidence_normalization_aliases_v1.tsv" "${FAKE_ROOT}/config/evidence_normalization_aliases_v1.tsv"
cat > "${FAKE_ROOT}/config/trust/generated/medical_runtime.txt" <<'EOF'
medlineplus.gov
dailymed.nlm.nih.gov
pubmed.ncbi.nlm.nih.gov
EOF

cp "${REAL_ROOT}/tools/evidence_session.sh" "${FAKE_ROOT}/tools/evidence_session.sh"
cp "${REAL_ROOT}/tools/build_evidence_pack.sh" "${FAKE_ROOT}/tools/build_evidence_pack.sh"
cp "${REAL_ROOT}/tools/fetch_key.sh" "${FAKE_ROOT}/tools/fetch_key.sh"
cp "${REAL_ROOT}/tools/router/medical_query_heuristics.py" "${FAKE_ROOT}/tools/router/medical_query_heuristics.py"
cp "${REAL_ROOT}/tools/router/extract_medical_fact.py" "${FAKE_ROOT}/tools/router/extract_medical_fact.py"
cp "${REAL_ROOT}/tools/router/core/medical_query_heuristics.py" "${FAKE_ROOT}/tools/router/core/medical_query_heuristics.py"
cp "${REAL_ROOT}/tools/router/core/medical_fact_extractor.py" "${FAKE_ROOT}/tools/router/core/medical_fact_extractor.py"

cat > "${FAKE_ROOT}/tools/fetch_url_allowlisted.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
url="${1:-}"
case "${url}" in
  https://medlineplus.gov/search/\?query=lisinopril)
    echo "FETCH_META status=200" >&2
    cat <<'EOF'
LISINOPRIL
USES
Used to treat high blood pressure.
DOSAGE AND ADMINISTRATION
Initial adult dose: 10 mg once daily.
EOF
    ;;
  https://dailymed.nlm.nih.gov/dailymed/search.cfm\?query=lisinopril)
    echo "FETCH_META status=200" >&2
    cat <<'EOF'
DOSAGE AND ADMINISTRATION
Usual adult dose is 10 mg once daily.
CONTRAINDICATIONS
Contraindicated in patients with hypersensitivity to lisinopril.
EOF
    ;;
  https://pubmed.ncbi.nlm.nih.gov/\?term=lisinopril)
    echo "FETCH_META status=200" >&2
    printf 'Review article describing lisinopril 10 mg once daily for hypertension.\n'
    ;;
  *)
    echo "unexpected URL: ${url}" >&2
    exit 2
    ;;
esac
SH

cat > "${FAKE_ROOT}/tools/compose_from_evidence.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf 'compose should not run\n'
exit 97
SH

cat > "${FAKE_ROOT}/tools/print_validated.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
cat
SH

chmod +x \
  "${FAKE_ROOT}/tools/evidence_session.sh" \
  "${FAKE_ROOT}/tools/build_evidence_pack.sh" \
  "${FAKE_ROOT}/tools/fetch_key.sh" \
  "${FAKE_ROOT}/tools/fetch_url_allowlisted.sh" \
  "${FAKE_ROOT}/tools/compose_from_evidence.sh" \
  "${FAKE_ROOT}/tools/print_validated.sh" \
  "${FAKE_ROOT}/tools/router/medical_query_heuristics.py"

out="$(LUCY_ROOT="${FAKE_ROOT}" LUCY_ROUTER_BYPASS=1 LUCY_CHAT_FORCE_MODE=EVIDENCE LUCY_FETCH_URL_TOOL="${FAKE_ROOT}/tools/fetch_url_allowlisted.sh" "${LUCY_CHAT}" "Dose of lisinopril?")"
printf '%s\n' "${out}" | grep -q "The retrieved evidence for lisinopril includes this dosing statement: Usual adult dose is 10 mg once daily" || die "missing structured dose answer"
printf '%s\n' "${out}" | grep -q "This is general information from the current evidence pack" || die "missing dose safety framing"
printf '%s\n' "${out}" | grep -q "medlineplus.gov" || die "missing medlineplus source"
printf '%s\n' "${out}" | grep -q "dailymed.nlm.nih.gov" || die "missing dailymed source"
printf '%s\n' "${out}" | grep -q "pubmed.ncbi.nlm.nih.gov" || die "missing pubmed source"
[[ "$(read_field OUTCOME_CODE)" == "answered" ]] || die "expected OUTCOME_CODE=answered"
[[ "$(read_field MEDICAL_STRUCTURED_STATUS)" == "answered" ]] || die "expected MEDICAL_STRUCTURED_STATUS=answered"
[[ "$(read_field MEDICAL_STRUCTURED_QUERY_FAMILY)" == "dose" ]] || die "expected MEDICAL_STRUCTURED_QUERY_FAMILY=dose"

ok "bounded extractor emits deterministic dose answer without compose fallback"
echo "PASS: test_lucy_chat_dynamic_medication_dose_structured_extract"
