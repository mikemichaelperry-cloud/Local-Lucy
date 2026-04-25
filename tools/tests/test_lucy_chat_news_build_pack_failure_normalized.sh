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
news_world_1
EOF

cat > "${FAKE_ROOT}/config/query_to_keys_v1.tsv" <<'EOF'
latest world news	NEWS	news_world_1
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
echo "ERROR: no evidence items fetched" >&2
exit 2
SH

cat > "${FAKE_ROOT}/tools/build_news_digest.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf 'should not run\n'
SH

cat > "${FAKE_ROOT}/tools/news_answer_deterministic.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf 'should not run\n'
SH

cat > "${FAKE_ROOT}/tools/enforce_news_plurality.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
exit 0
SH

chmod +x "${FAKE_ROOT}/tools/"*

out="$(LUCY_ROOT="${FAKE_ROOT}" LUCY_ROUTER_BYPASS=1 LUCY_CHAT_FORCE_MODE=NEWS "${LUCY_CHAT}" "latest world news")"
printf '%s\n' "${out}" | grep -q "Unable to answer from current evidence." || die "missing normalized news failure"
[[ "$(read_field OUTCOME_CODE)" == "validation_failed" ]] || die "expected OUTCOME_CODE=validation_failed"
[[ "$(read_field EVIDENCE_CREATED)" == "true" ]] || die "expected EVIDENCE_CREATED=true"
sid="$(read_field SESSION_ID)"
[[ -n "${sid}" ]] || die "expected SESSION_ID"
[[ -f "${FAKE_ROOT}/evidence/${sid}/pack/build_pack.stderr" ]] || die "missing captured build_pack stderr"
ok "news build-pack failure is normalized and preserves evidence metadata"

echo "PASS: test_lucy_chat_news_build_pack_failure_normalized"
