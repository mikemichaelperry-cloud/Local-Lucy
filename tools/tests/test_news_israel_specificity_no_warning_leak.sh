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

cat > "${FAKE_ROOT}/config/evidence_keys_allowlist.txt" <<'EOF'
news_israel_1
news_israel_2
news_israel_only_1
news_israel_only_2
news_world_1
news_world_2
EOF

cat > "${FAKE_ROOT}/config/query_to_keys_v1.tsv" <<'EOF'
latest israel news	NEWS	news_israel_1 news_israel_2
latest news from only israeli sources	NEWS	news_israel_only_1 news_israel_only_2
news	NEWS	news_world_1 news_world_2
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
echo "WARN: fetch failed for key: news_world_1" >&2
echo "FETCH_META final_domain=feeds.example.org reason=FAIL_NOT_ALLOWLISTED" >&2
cat > "${out_dir}/evidence_pack.txt" <<'EOF'
BEGIN_EVIDENCE_ITEM
DOMAIN=jpost.com
TITLE: Headline A
DATE: Thu, 26 Feb 2026 19:32:08 GMT
END_EVIDENCE_ITEM
====
BEGIN_EVIDENCE_ITEM
DOMAIN=timesofisrael.com
TITLE: Headline B
DATE: Thu, 26 Feb 2026 18:23:43 +0000
END_EVIDENCE_ITEM
====
EOF
printf 'jpost.com\ntimesofisrael.com\n' > "${out_dir}/domains.txt"
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
Summary: Latest items extracted from allowlisted sources as of 2026-02-26T19:07:36Z.
Key items:
- [jpost.com] : Headline A
- [timesofisrael.com] : Headline B
Conflicts/uncertainty: None assessed (deterministic extract only; no cross-article reconciliation).
Sources:
- jpost.com
- timesofisrael.com
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

run_out="$(
  LUCY_ROOT="${FAKE_ROOT}" \
  LUCY_ROUTER_BYPASS=1 \
  LUCY_CHAT_FORCE_MODE=NEWS \
  "${LUCY_CHAT}" "Whats the latest Israel news?" 2>&1
)" || die "lucy_chat failed: ${run_out}"

printf '%s\n' "${run_out}" | grep -q 'Headline A' || die "expected deterministic news body to reach user output"
printf '%s\n' "${run_out}" | grep -qi 'WARN: fetch failed' && die "warning leakage should not reach user output"
printf '%s\n' "${run_out}" | grep -qi 'FETCH_META' && die "FETCH_META leakage should not reach user output"
ok "news path suppresses pack-builder warnings from user-facing output"

sid="$(awk -F= '$1=="SESSION_ID"{print $2; exit}' "${FAKE_ROOT}/state/last_route.env")"
[[ -n "${sid}" ]] || die "missing session id in last_route.env"
state_json="${FAKE_ROOT}/state/evidence_session_${sid}.json"
[[ -f "${state_json}" ]] || die "missing evidence session state"
keys="$(python3 - "${state_json}" <<'PY'
import json,sys
obj=json.load(open(sys.argv[1], 'r', encoding='utf-8'))
print(' '.join(obj.get('keys') or []))
PY
)"
printf '%s\n' "${keys}" | grep -q 'news_israel_1' || die "expected israel key"
printf '%s\n' "${keys}" | grep -q 'news_israel_2' || die "expected israel key"
printf '%s\n' "${keys}" | grep -q 'news_world_' && die "specific israel mapping should prevent generic news key accumulation"
ok "israel-news mapping specificity prevents generic news key contamination"

strict_plan="$("${FAKE_ROOT}/tools/router/classify_intent.py" "What is the latest news from only Israeli sources?")"
strict_allow="$(python3 - "${strict_plan}" <<'PY'
import json,sys
print(json.loads(sys.argv[1]).get("allow_domains_file","") or "")
PY
)"
[[ "${strict_allow}" == "config/trust/generated/news_israel_only_runtime.txt" ]] || die "strict Israeli-source request should route to news_israel_only_runtime.txt (got: ${strict_allow})"
ok "strict Israeli-source query routes to Israeli-only domain allowlist"

typo_plan="$("${FAKE_ROOT}/tools/router/classify_intent.py" "Whats the latest Iraeli news?")"
typo_allow="$(python3 - "${typo_plan}" <<'PY'
import json,sys
print(json.loads(sys.argv[1]).get("allow_domains_file","") or "")
PY
)"
[[ "${typo_allow}" == "config/trust/generated/news_israel_runtime.txt" ]] || die "Iraeli typo should still route to Israel news allowlist (got: ${typo_allow})"
ok "Iraeli typo normalizes into Israel news routing"

echo "PASS: test_news_israel_specificity_no_warning_leak"
