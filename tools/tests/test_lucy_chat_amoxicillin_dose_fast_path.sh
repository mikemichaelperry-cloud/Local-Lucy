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
medical_amoxicillin_1
medical_amoxicillin_2
EOF

cat > "${FAKE_ROOT}/config/query_to_keys_v1.tsv" <<'EOF'
amoxicillin	EVIDENCE	medical_amoxicillin_1 medical_amoxicillin_2
amoxycilin	EVIDENCE	medical_amoxicillin_1 medical_amoxicillin_2
EOF

cat > "${FAKE_ROOT}/config/evidence_normalization_aliases_v1.tsv" <<'EOF'
medical	EVIDENCE	high	\bamoxycilin\b	amoxicillin
medical	EVIDENCE	medium	\bdosage\b	dose
EOF

cat > "${FAKE_ROOT}/tools/evidence_session.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  clear|add|list) exit 0 ;;
esac
SH

cat > "${FAKE_ROOT}/tools/build_evidence_pack.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
out_dir="${1:?outdir}"
mkdir -p "${out_dir}"
cat > "${out_dir}/evidence_pack.txt" <<'EOF'
BEGIN_EVIDENCE_ITEM
DOMAIN=dailymed.nlm.nih.gov
END_EVIDENCE_ITEM
====
BEGIN_EVIDENCE_ITEM
DOMAIN=medlineplus.gov
END_EVIDENCE_ITEM
EOF
cat > "${out_dir}/domains.txt" <<'EOF'
dailymed.nlm.nih.gov
medlineplus.gov
EOF
SH

cat > "${FAKE_ROOT}/tools/compose_from_evidence.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf 'should not run\n'
SH

cat > "${FAKE_ROOT}/tools/print_validated.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
cat
SH

chmod +x "${FAKE_ROOT}/tools/"*
cp "${REAL_ROOT}/tools/evidence_normalizer.py" "${FAKE_ROOT}/tools/evidence_normalizer.py"
chmod +x "${FAKE_ROOT}/tools/evidence_normalizer.py"

out="$(LUCY_ROOT="${FAKE_ROOT}" LUCY_ROUTER_BYPASS=1 LUCY_CHAT_FORCE_MODE=EVIDENCE "${LUCY_CHAT}" "What is the standard dose of amoxycilin for a serious infection?")"
printf '%s\n' "${out}" | grep -q "500 mg every 8 hours or 875 mg every 12 hours" || die "missing amoxicillin dosing answer"
printf '%s\n' "${out}" | grep -q "dailymed.nlm.nih.gov" || die "missing dailymed source"
printf '%s\n' "${out}" | grep -q "medlineplus.gov" || die "missing medlineplus source"
[[ "$(read_field OUTCOME_CODE)" == "answered" ]] || die "expected OUTCOME_CODE=answered"
[[ "$(read_field EVIDENCE_NORMALIZER_DETECTOR_FIRED)" == "true" ]] || die "expected detector fired"
[[ "$(read_field EVIDENCE_NORMALIZER_SELECTED_DOMAIN)" == "medical" ]] || die "expected medical selected domain"
[[ "$(read_field EVIDENCE_NORMALIZER_SELECTED_QUERY)" == *"amoxicillin"* ]] || die "expected normalized amoxicillin query"
ok "amoxicillin dose query uses deterministic medical evidence fast-path"

echo "PASS: test_lucy_chat_amoxicillin_dose_fast_path"
