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
news_israel_1
news_israel_2
news_world_1
medical_cialis_1
medical_cialis_2
EOF

cat > "${FAKE_ROOT}/config/query_to_keys_v1.tsv" <<'EOF'
tadalafil	EVIDENCE	medical_cialis_1 medical_cialis_2
latest world news	NEWS	news_world_1
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
printf 'BEGIN_EVIDENCE_ITEM\nDOMAIN=example.com\nEND_EVIDENCE_ITEM\n' > "${out_dir}/evidence_pack.txt"
printf 'example.com\n' > "${out_dir}/domains.txt"
SH

cat > "${FAKE_ROOT}/tools/compose_from_evidence.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf 'Answer: stub\nSources: example.com\n'
SH

cat > "${FAKE_ROOT}/tools/print_validated.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
cat
SH

chmod +x "${FAKE_ROOT}/tools/"*

set +e
out="$(LUCY_ROOT="${FAKE_ROOT}" LUCY_ROUTER_BYPASS=1 LUCY_CHAT_FORCE_MODE=EVIDENCE "${LUCY_CHAT}" "What is the standard dose of amoxycilin for a serious infection?" 2>&1)"
rc=$?
set -e

[[ "${rc}" == "0" ]] || die "expected lucy_chat to normalize unmatched evidence query"
[[ -f "${FAKE_ROOT}/state/added_keys.log" ]] || die "missing added_keys.log"
[[ ! -s "${FAKE_ROOT}/state/added_keys.log" ]] || die "unexpected fallback keys selected: $(cat "${FAKE_ROOT}/state/added_keys.log")"
printf '%s\n' "${out}" | grep -q "Unable to answer from current evidence." || die "missing normalized evidence miss"
printf '%s\n' "${out}" | grep -q "Action: provide a narrower query or an allowlisted source URL." || die "missing narrowing guidance"
ok "unmatched evidence query is normalized without silently falling back to unrelated news keys"

echo "PASS: test_lucy_chat_evidence_unmatched_query_no_news_fallback"
