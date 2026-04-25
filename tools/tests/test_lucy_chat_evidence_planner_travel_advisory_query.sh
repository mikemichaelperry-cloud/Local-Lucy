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
travel_egypt_1
EOF

cat > "${FAKE_ROOT}/config/query_to_keys_v1.tsv" <<'EOF'
is it safe now to travel to egypt	EVIDENCE	travel_egypt_1
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
printf 'BEGIN_EVIDENCE_ITEM\nDOMAIN=travel.state.gov\nEND_EVIDENCE_ITEM\n' > "${out_dir}/evidence_pack.txt"
printf 'travel.state.gov\n' > "${out_dir}/domains.txt"
SH

cat > "${FAKE_ROOT}/tools/compose_from_evidence.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf 'Answer: Egypt travel advisory stub\nSources: travel.state.gov\n'
SH

cat > "${FAKE_ROOT}/tools/print_validated.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
cat
SH

cp "${REAL_ROOT}/tools/evidence_planner.py" "${FAKE_ROOT}/tools/evidence_planner.py"
cp "${REAL_ROOT}/tools/evidence_normalizer.py" "${FAKE_ROOT}/tools/evidence_normalizer.py"
chmod +x "${FAKE_ROOT}/tools/"*

out="$(LUCY_ROOT="${FAKE_ROOT}" LUCY_ROUTER_BYPASS=1 LUCY_CHAT_FORCE_MODE=EVIDENCE "${LUCY_CHAT}" "Do I need a travel advisory check for Egypt today?")"
printf '%s\n' "${out}" | grep -q "Egypt travel advisory stub" || die "missing travel evidence answer"
grep -Fxq "travel_egypt_1" "${FAKE_ROOT}/state/added_keys.log" || die "expected planner-selected travel key"
[[ "$(read_field EVIDENCE_PLANNER_FIRED)" == "true" ]] || die "expected planner fired"
[[ "$(read_field EVIDENCE_PLANNER_SELECTED_ADAPTER)" == "travel" ]] || die "expected travel planner adapter"
[[ "$(read_field EVIDENCE_PLANNER_SELECTED_QUERY)" == "Is it safe now to travel to Egypt?" ]] || die "expected planned travel query"
ok "travel advisory wording is planned into a retrieval-friendly evidence query"

echo "PASS: test_lucy_chat_evidence_planner_travel_advisory_query"
