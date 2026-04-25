#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REAL_ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"
BUILD_PACK="${REAL_ROOT}/tools/build_evidence_pack.sh"

ok(){ echo "OK: $*"; }
die(){ echo "FAIL: $*" >&2; exit 1; }

[[ -x "${BUILD_PACK}" ]] || die "missing build_evidence_pack.sh"

TMPD="$(mktemp -d)"
trap 'rm -rf "${TMPD}"' EXIT

FAKE_ROOT="${TMPD}/root"
STATE_DIR="${FAKE_ROOT}/state"
CACHE_DIR="${FAKE_ROOT}/cache/evidence"
OUT_DIR="${TMPD}/out"
PROFILE_FILE="${TMPD}/latency.tsv"

mkdir -p "${FAKE_ROOT}/tools/router" "${STATE_DIR}" "${CACHE_DIR}"
cp "${REAL_ROOT}/tools/router/latency_profile.sh" "${FAKE_ROOT}/tools/router/latency_profile.sh"

cat > "${STATE_DIR}/evidence_session_parallel.json" <<'EOF'
{"session_id":"parallel","keys":["alpha","beta","gamma"]}
EOF

cat > "${FAKE_ROOT}/tools/fetch_key.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail

key="${1:?key}"
case "${key}" in
  alpha)
    sleep 0.60
    dom="alpha.example"
    text="Alpha body"
    ;;
  beta)
    sleep 0.10
    dom="beta.example"
    text="Beta body"
    ;;
  gamma)
    sleep 0.20
    dom="gamma.example"
    text="Gamma body"
    ;;
  *)
    exit 2
    ;;
esac

printf 'KEY=%s\n' "${key}" >&2
printf 'DOMAIN=%s\n' "${dom}" >&2
printf 'FETCH_META final_url=https://%s/ total_time_ms=1\n' "${dom}" >&2
printf '%s\n' "${text}"
SH
chmod +x "${FAKE_ROOT}/tools/fetch_key.sh"

start_ms="$(date +%s%3N)"
LUCY_ROOT="${FAKE_ROOT}" \
LUCY_SESSION_ID="parallel" \
LUCY_STATE_DIR="${STATE_DIR}" \
LUCY_CACHE_DIR="${CACHE_DIR}" \
LUCY_TOOLS_DIR="${FAKE_ROOT}/tools" \
LUCY_EVIDENCE_FETCH_JOBS=3 \
LUCY_LATENCY_PROFILE_ACTIVE=1 \
LUCY_LATENCY_PROFILE_FILE="${PROFILE_FILE}" \
LUCY_LATENCY_RUN_ID="parallel_fetch" \
"${BUILD_PACK}" "${OUT_DIR}" >/dev/null
end_ms="$(date +%s%3N)"
elapsed_ms="$((end_ms - start_ms))"

mapfile -t pack_keys < <(awk -F= '/^KEY=/{print $2}' "${OUT_DIR}/evidence_pack.txt")
[[ "${#pack_keys[@]}" -eq 3 ]] || die "expected 3 keys in evidence pack"
[[ "${pack_keys[0]}" == "alpha" ]] || die "expected alpha first in pack"
[[ "${pack_keys[1]}" == "beta" ]] || die "expected beta second in pack"
[[ "${pack_keys[2]}" == "gamma" ]] || die "expected gamma third in pack"
ok "evidence pack preserves key order"

grep -Fq 'Alpha body' "${OUT_DIR}/evidence_pack.txt" || die "missing alpha body"
grep -Fq 'Beta body' "${OUT_DIR}/evidence_pack.txt" || die "missing beta body"
grep -Fq 'Gamma body' "${OUT_DIR}/evidence_pack.txt" || die "missing gamma body"
ok "evidence pack includes all fetched bodies"

fetch_key_count="$(rg -c 'component=build_evidence_pack\tstage=fetch_key' "${PROFILE_FILE}")"
[[ "${fetch_key_count}" == "3" ]] || die "expected 3 build_evidence_pack fetch_key latency entries"
ok "latency profile records one fetch_key entry per fetched key"

[[ "${elapsed_ms}" -lt 850 ]] || die "expected parallel fetch wall time under 850ms, got ${elapsed_ms}ms"
ok "parallel fetch wall time improved over sequential sum"

echo "PASS: test_build_evidence_pack_parallel_deterministic_order"
