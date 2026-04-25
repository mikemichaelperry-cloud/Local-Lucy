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
medical_hypertension_1
medical_hypertension_2
EOF

cat > "${FAKE_ROOT}/config/query_to_keys_v1.tsv" <<'EOF'
medication for high blood pressure	EVIDENCE	medical_hypertension_1 medical_hypertension_2
what is the correct medication for high blood pressure	EVIDENCE	medical_hypertension_1 medical_hypertension_2
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
DOMAIN=medlineplus.gov
END_EVIDENCE_ITEM
====
BEGIN_EVIDENCE_ITEM
DOMAIN=pubmed.ncbi.nlm.nih.gov
END_EVIDENCE_ITEM
EOF
cat > "${out_dir}/domains.txt" <<'EOF'
medlineplus.gov
pubmed.ncbi.nlm.nih.gov
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

out="$(LUCY_ROOT="${FAKE_ROOT}" LUCY_ROUTER_BYPASS=1 LUCY_CHAT_FORCE_MODE=EVIDENCE "${LUCY_CHAT}" "What is the correcft medication for high blood pressure?")"
printf '%s\n' "${out}" | grep -q "There is no single correct medication for high blood pressure." || die "missing hypertension medication answer"
printf '%s\n' "${out}" | grep -q "thiazide-type diuretics, ACE inhibitors, ARBs, and calcium channel blockers" || die "missing first-line classes"
printf '%s\n' "${out}" | grep -q "medlineplus.gov" || die "missing medlineplus source"
printf '%s\n' "${out}" | grep -q "pubmed.ncbi.nlm.nih.gov" || die "missing pubmed source"
[[ "$(read_field OUTCOME_CODE)" == "answered" ]] || die "expected OUTCOME_CODE=answered"
ok "hypertension medication query uses deterministic medical evidence fast-path"

echo "PASS: test_lucy_chat_hypertension_medication_fast_path"
