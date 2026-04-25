#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REAL_ROOT="${LUCY_ROOT:-$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)}"
LUCY_CHAT="${REAL_ROOT}/lucy_chat.sh"

ok(){ echo "OK: $*"; }
die(){ echo "FAIL: $*" >&2; exit 1; }

[[ -x "${LUCY_CHAT}" ]] || die "missing executable: ${LUCY_CHAT}"

TMPD="$(mktemp -d)"
trap 'rm -rf "${TMPD}"' EXIT
FAKE_ROOT="${TMPD}/root"
mkdir -p "${FAKE_ROOT}/tools" "${FAKE_ROOT}/config" "${FAKE_ROOT}/state" "${FAKE_ROOT}/evidence" "${FAKE_ROOT}/cache/evidence"

cat > "${FAKE_ROOT}/config/evidence_keys_allowlist.txt" <<'EOF'
medical_amoxicillin_1
EOF

cat > "${FAKE_ROOT}/config/query_to_keys_v1.tsv" <<'EOF'
amoxicillin	EVIDENCE	medical_amoxicillin_1
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
EOF
cat > "${out_dir}/domains.txt" <<'EOF'
medlineplus.gov
EOF
SH

cat > "${FAKE_ROOT}/tools/compose_from_evidence.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
cat <<'EOF'
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
SH

cat > "${FAKE_ROOT}/tools/print_validated.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
cat
SH

chmod +x "${FAKE_ROOT}/tools/"*

out="$(LUCY_ROOT="${FAKE_ROOT}" LUCY_ROUTER_BYPASS=1 LUCY_CHAT_FORCE_MODE=EVIDENCE "${LUCY_CHAT}" "What is Amoxicillin?")"
printf '%s\n' "${out}" | grep -Fxq "BEGIN_VALIDATED" || die "missing BEGIN_VALIDATED"
printf '%s\n' "${out}" | grep -Fxq "END_VALIDATED" || die "missing END_VALIDATED"
printf '%s\n' "${out}" | grep -Fq "Amoxicillin is a broad-spectrum antibiotic used to treat various bacterial infections." \
  || die "missing sanitized answer"

if printf '%s\n' "${out}" | grep -Eqi 'Evidence:|Oscar is Mike.?s dog|MEMORY PROPOSAL|type: entity|type: drug information|subject: Amoxicillin|confidence: high'; then
  die "validated output leaked evidence/proposal noise"
fi

ok "lucy_chat validated wrapper strips leaked proposal noise"

echo "PASS: test_lucy_chat_validated_sanitizes_proposal_noise"
