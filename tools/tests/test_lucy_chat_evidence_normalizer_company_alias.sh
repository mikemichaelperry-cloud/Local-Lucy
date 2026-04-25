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
company_alphabet_1
EOF

cat > "${FAKE_ROOT}/config/query_to_keys_v1.tsv" <<'EOF'
alphabet stock	EVIDENCE	company_alphabet_1
EOF

cat > "${FAKE_ROOT}/config/evidence_normalization_aliases_v1.tsv" <<'EOF'
finance	EVIDENCE	high	\bgoogle stock\b	alphabet stock
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
printf 'BEGIN_EVIDENCE_ITEM\nDOMAIN=finance.example.com\nEND_EVIDENCE_ITEM\n' > "${out_dir}/evidence_pack.txt"
printf 'finance.example.com\n' > "${out_dir}/domains.txt"
SH

cat > "${FAKE_ROOT}/tools/compose_from_evidence.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf 'Answer: Alphabet evidence stub\nSources: finance.example.com\n'
SH

cat > "${FAKE_ROOT}/tools/print_validated.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
cat
SH

chmod +x "${FAKE_ROOT}/tools/"*
cp "${REAL_ROOT}/tools/evidence_normalizer.py" "${FAKE_ROOT}/tools/evidence_normalizer.py"
chmod +x "${FAKE_ROOT}/tools/evidence_normalizer.py"

out="$(LUCY_ROOT="${FAKE_ROOT}" LUCY_ROUTER_BYPASS=1 LUCY_CHAT_FORCE_MODE=EVIDENCE "${LUCY_CHAT}" "What is the google stock outlook?")"
printf '%s\n' "${out}" | grep -q "Alphabet evidence stub" || die "missing composed evidence answer"
grep -Fxq "company_alphabet_1" "${FAKE_ROOT}/state/added_keys.log" || die "expected normalized company key"
[[ "$(read_field OUTCOME_CODE)" == "answered" ]] || die "expected OUTCOME_CODE=answered"
[[ "$(read_field EVIDENCE_NORMALIZER_DETECTOR_FIRED)" == "true" ]] || die "expected detector fired"
[[ "$(read_field EVIDENCE_NORMALIZER_SELECTED_DOMAIN)" == "finance" ]] || die "expected finance selected domain"
[[ "$(read_field EVIDENCE_NORMALIZER_SELECTED_QUERY)" == *"alphabet stock"* ]] || die "expected normalized company query"
[[ "$(read_field EVIDENCE_NORMALIZER_MATCH_KIND)" == "mapping_phrase" ]] || die "expected mapping_phrase match kind"
ok "non-medical company alias normalization routes through the generic evidence normalizer"

echo "PASS: test_lucy_chat_evidence_normalizer_company_alias"
