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
medical_cialis_1
EOF

cat > "${FAKE_ROOT}/config/query_to_keys_v1.tsv" <<'EOF'
tadalafil	EVIDENCE	medical_cialis_1
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
echo "WARN: fetch failed for key: medical_cialis_1" >&2
echo "FETCH_META final_url=https://example.test/medical_cialis_1 final_domain=example.test http_status=000 reason=FAIL_DNS bytes=0 total_time_ms=0 attempts=2 proto=http2_fallback_http1.1 redirect_count=0 allowlisted_final=true attempt1_status=000 attempt1_reason=FAIL_DNS attempt1_proto=http2 attempt2_status=000 attempt2_reason=FAIL_DNS attempt2_proto=http1.1" >&2
echo "ERROR: no evidence items fetched" >&2
exit 2
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

out="$(LUCY_ROOT="${FAKE_ROOT}" LUCY_ROUTER_BYPASS=1 LUCY_CHAT_FORCE_MODE=EVIDENCE "${LUCY_CHAT}" "What is tadalafil used for?")"
printf '%s\n' "${out}" | grep -q "Unable to answer from current evidence." || die "missing normalized evidence failure"
printf '%s\n' "${out}" | grep -q "Action: retry later or provide an allowlisted source URL." || die "missing retry guidance"
[[ "$(read_field OUTCOME_CODE)" == "validation_failed" ]] || die "expected OUTCOME_CODE=validation_failed"
[[ "$(read_field EVIDENCE_CREATED)" == "true" ]] || die "expected EVIDENCE_CREATED=true"
[[ "$(read_field EVIDENCE_FETCH_FAILURE_REASON)" == "fail_dns" ]] || die "expected EVIDENCE_FETCH_FAILURE_REASON=fail_dns"
[[ "$(read_field EVIDENCE_FETCH_FAILED_KEYS)" == "medical_cialis_1" ]] || die "expected failed key diagnostic"
[[ "$(read_field EVIDENCE_FETCH_FAIL_DNS_COUNT)" == "1" ]] || die "expected DNS failure count"
sid="$(read_field SESSION_ID)"
[[ -n "${sid}" ]] || die "expected SESSION_ID"
[[ -f "${FAKE_ROOT}/evidence/${sid}/pack/build_pack.stderr" ]] || die "missing captured build_pack stderr"
ok "evidence build-pack failure is normalized and records fetch-failure diagnostics"

echo "PASS: test_lucy_chat_evidence_build_pack_failure_normalized"
