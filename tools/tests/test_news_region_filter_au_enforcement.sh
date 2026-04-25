#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REAL_ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"
LUCY_CHAT="${REAL_ROOT}/lucy_chat.sh"

ok(){ echo "OK: $*"; }
die(){ echo "FAIL: $*" >&2; exit 1; }

[[ -x "${LUCY_CHAT}" ]] || die "missing lucy_chat.sh"

TMPD="$(mktemp -d)"
trap 'rm -rf "${TMPD}"' EXIT
FAKE_ROOT="${TMPD}/root"
mkdir -p "${FAKE_ROOT}/tools" "${FAKE_ROOT}/tools/router/core" "${FAKE_ROOT}/config" "${FAKE_ROOT}/state" "${FAKE_ROOT}/evidence" "${FAKE_ROOT}/cache/evidence"

cp "${REAL_ROOT}/tools/router/classify_intent.py" "${FAKE_ROOT}/tools/router/classify_intent.py"
cp "${REAL_ROOT}/tools/router/plan_to_pipeline.py" "${FAKE_ROOT}/tools/router/plan_to_pipeline.py"
cp "${REAL_ROOT}/tools/router/policy_engine.py" "${FAKE_ROOT}/tools/router/policy_engine.py"
cp "${REAL_ROOT}/tools/router/core/"*.py "${FAKE_ROOT}/tools/router/core/"

cat > "${FAKE_ROOT}/config/query_to_keys_v1.tsv" <<'EOF'
news	NEWS	news_world_1 news_world_2
news about australia	NEWS	news_au_1 news_au_2 news_world_1 news_world_2
australian news	NEWS	news_au_1 news_au_2 news_world_1 news_world_2
latest australian news	NEWS	news_au_1 news_au_2 news_world_1 news_world_2
EOF

cat > "${FAKE_ROOT}/tools/evidence_session.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
STATE_DIR="${LUCY_STATE_DIR:?}"
sid="${LUCY_SESSION_ID:-default}"
f="${STATE_DIR}/evidence_session_${sid}.json"
case "${1:-}" in
  clear)
    printf '{"session_id":"%s","keys":[]}\n' "${sid}" > "${f}"
    ;;
  add)
    shift
    keys_json="$(python3 - "$@" <<'PY'
import json, sys
print(json.dumps([x for x in sys.argv[1:] if x.strip()]))
PY
)"
    printf '{"session_id":"%s","keys":%s}\n' "${sid}" "${keys_json}" > "${f}"
    ;;
  list)
    cat "${f}" 2>/dev/null || true
    ;;
  *)
    exit 0
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
DOMAIN=abc.net.au
TITLE: AU headline
END_EVIDENCE_ITEM
====
BEGIN_EVIDENCE_ITEM
DOMAIN=smh.com.au
TITLE: AU headline 2
END_EVIDENCE_ITEM
====
EOF
printf 'abc.net.au\nsmh.com.au\n' > "${out_dir}/domains.txt"
SH

cat > "${FAKE_ROOT}/tools/build_news_digest.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
cp "${1:?pack}" "${2:?digest}"
SH

cat > "${FAKE_ROOT}/tools/news_answer_deterministic.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
cat <<'EOF'
BEGIN_VALIDATED
Summary: AU news digest mock.
Sources:
- abc.net.au
- smh.com.au
END_VALIDATED
EOF
SH

cat > "${FAKE_ROOT}/tools/enforce_news_plurality.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
exit 0
SH

chmod +x "${FAKE_ROOT}/tools/"*
chmod +x "${FAKE_ROOT}/tools/router/"*.py

write_allowlist_with_au(){
  cat > "${FAKE_ROOT}/config/evidence_keys_allowlist.txt" <<'EOF'
news_au_1
news_au_2
news_world_1
news_world_2
EOF
}

write_allowlist_world_only(){
  cat > "${FAKE_ROOT}/config/evidence_keys_allowlist.txt" <<'EOF'
news_world_1
news_world_2
EOF
}

run_query(){
  local q="$1"
  LUCY_ROOT="${FAKE_ROOT}" LUCY_ROUTER_BYPASS=1 "${LUCY_CHAT}" "${q}" 2>&1
}

write_allowlist_with_au
out1="$(run_query "Whats the latest Australian news?")" || die "AU query failed: ${out1}"
printf '%s\n' "${out1}" | grep -q 'AU news digest mock' || die "expected AU mock digest output"
sid1="$(awk -F= '$1=="SESSION_ID"{print $2; exit}' "${FAKE_ROOT}/state/last_route.env")"
[[ -n "${sid1}" ]] || die "missing session id for AU test"
keys1="$(python3 - "${FAKE_ROOT}/state/evidence_session_${sid1}.json" <<'PY'
import json, sys
print(" ".join(json.load(open(sys.argv[1], "r", encoding="utf-8")).get("keys") or []))
PY
)"
printf '%s\n' "${keys1}" | grep -q 'news_au_1' || die "expected AU key"
printf '%s\n' "${keys1}" | grep -q 'news_au_2' || die "expected AU key"
printf '%s\n' "${keys1}" | grep -q 'news_world_' && die "region filter should exclude world keys for AU prompts"
ok "AU region-filtered news excludes world fallback keys"

out1b="$(run_query "news about Australia housing")" || die "AU housing query failed: ${out1b}"
sid1b="$(awk -F= '$1=="SESSION_ID"{print $2; exit}' "${FAKE_ROOT}/state/last_route.env")"
[[ -n "${sid1b}" ]] || die "missing session id for AU housing test"
keys1b="$(python3 - "${FAKE_ROOT}/state/evidence_session_${sid1b}.json" <<'PY'
import json, sys
print(" ".join(json.load(open(sys.argv[1], "r", encoding="utf-8")).get("keys") or []))
PY
)"
printf '%s\n' "${keys1b}" | grep -q 'news_au_1' || die "expected AU key for AU housing query"
printf '%s\n' "${keys1b}" | grep -q 'news_au_2' || die "expected AU key for AU housing query"
printf '%s\n' "${keys1b}" | grep -q 'news_world_' && die "AU housing query should not prefer world keys when AU keys exist"
ok "AU housing query prefers AU keys when AU keys exist"

write_allowlist_world_only
out2="$(run_query "Whats the latest Australian news?")" || die "AU no-config query failed: ${out2}"
printf '%s\n' "${out2}" | grep -q 'AU news digest mock' || die "expected fallback digest output (got: ${out2})"
sid2="$(awk -F= '$1=="SESSION_ID"{print $2; exit}' "${FAKE_ROOT}/state/last_route.env")"
[[ -n "${sid2}" ]] || die "missing session id for AU fallback test"
keys2="$(python3 - "${FAKE_ROOT}/state/evidence_session_${sid2}.json" <<'PY'
import json, sys
print(" ".join(json.load(open(sys.argv[1], "r", encoding="utf-8")).get("keys") or []))
PY
)"
printf '%s\n' "${keys2}" | grep -q 'news_world_1' || die "expected world fallback key"
printf '%s\n' "${keys2}" | grep -q 'news_world_2' || die "expected world fallback key"
ok "AU region with no configured feeds falls back to world news keys"

out3="$(run_query "news about Australia housing")" || die "AU housing no-config query failed: ${out3}"
sid3="$(awk -F= '$1=="SESSION_ID"{print $2; exit}' "${FAKE_ROOT}/state/last_route.env")"
[[ -n "${sid3}" ]] || die "missing session id for AU housing fallback test"
keys3="$(python3 - "${FAKE_ROOT}/state/evidence_session_${sid3}.json" <<'PY'
import json, sys
print(" ".join(json.load(open(sys.argv[1], "r", encoding="utf-8")).get("keys") or []))
PY
)"
printf '%s\n' "${keys3}" | grep -q 'news_world_1' || die "expected world fallback key for AU housing query"
printf '%s\n' "${keys3}" | grep -q 'news_world_2' || die "expected world fallback key for AU housing query"
ok "AU housing query falls back to world keys when AU keys are unavailable"

echo "PASS: test_news_region_filter_au_enforcement"
