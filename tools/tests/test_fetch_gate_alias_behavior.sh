#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"
GATE="${ROOT}/tools/internet/run_fetch_with_gate.sh"

ok(){ echo "OK: $*"; }
die(){ echo "FAIL: $*" >&2; exit 1; }

[[ -x "${GATE}" ]] || die "missing executable gate: ${GATE}"

TMPD="$(mktemp -d)"
trap 'rm -rf "${TMPD}"' EXIT
FAKEBIN="${TMPD}/bin"
mkdir -p "${FAKEBIN}"
REAL_PYTHON3="$(command -v python3)"

FILTER="${TMPD}/filter.txt"
cat > "${FILTER}" <<'EOF'
wikipedia.org
texasinstruments.com
EOF

cat > "${FAKEBIN}/curl" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
outfile=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -o) outfile="${2:-}"; shift 2 ;;
    --) shift; break ;;
    *) shift ;;
  esac
done
: "${outfile:?missing -o outfile}"
printf 'fake body\n' > "${outfile}"
final="${FAKE_CURL_FINAL_URL:-https://example.invalid/}"
printf 'http_status=200 final_url=%s total_time_s=0.001 size_download=9 redirect_count=0 http_version=2\n' "${final}"
SH
chmod +x "${FAKEBIN}/curl"

cat > "${FAKEBIN}/python3" <<SH
#!/usr/bin/env bash
set -euo pipefail
REAL_PYTHON3="${REAL_PYTHON3}"
if [[ "\${1:-}" == "${ROOT}/tools/internet/url_safety.py" && "\${2:-}" == "validate-url" ]]; then
  u="\${3:-}"
  case "\$u" in
    https://*) echo "OK url=\$u host=test port=443"; exit 0 ;;
    *) echo "ERR reason=https only"; exit 1 ;;
  esac
fi
exec "\$REAL_PYTHON3" "\$@"
SH
chmod +x "${FAKEBIN}/python3"

run_gate() {
  local url="$1"
  local final_url="${2:-$1}"
  local out rc
  set +e
  out="$(
    PATH="${FAKEBIN}:$PATH" \
    LUCY_FETCH_ALLOWLIST_FILTER_FILE="${FILTER}" \
    FAKE_CURL_FINAL_URL="${final_url}" \
    "${GATE}" "${url}" 2>&1
  )"
  rc=$?
  set -e
  printf '%s\n' "${rc}"
  printf '%s\n' "${out}"
}

# `www.` variant should pass when base domain is allowlisted.
res="$(run_gate "https://www.wikipedia.org/wiki/Test" "https://www.wikipedia.org/wiki/Test")"
rc="$(printf '%s\n' "${res}" | sed -n '1p')"
out="$(printf '%s\n' "${res}" | sed '1d')"
[[ "${rc}" == "0" ]] || die "expected rc=0 for www.wikipedia.org (got ${rc})"
printf '%s\n' "${out}" | grep -q 'allowlisted_final=true' || die "expected allowlisted_final=true for www.wikipedia.org"
ok "www variant allowed when base domain is allowlisted"

# Case-insensitive match should pass.
res="$(run_gate "https://WWW.WIKIPEDIA.ORG/wiki/Test" "https://WWW.WIKIPEDIA.ORG/wiki/Test")"
rc="$(printf '%s\n' "${res}" | sed -n '1p')"
[[ "${rc}" == "0" ]] || die "expected rc=0 for mixed-case host (got ${rc})"
ok "case-insensitive host match allowed"

# Trailing root dot should be normalized and pass.
res="$(run_gate "https://www.wikipedia.org./wiki/Test" "https://www.wikipedia.org./wiki/Test")"
rc="$(printf '%s\n' "${res}" | sed -n '1p')"
[[ "${rc}" == "0" ]] || die "expected rc=0 for trailing-dot host (got ${rc})"
ok "trailing-dot host normalized for allowlist match"

# Suffix attack must remain blocked.
res="$(run_gate "https://wikipedia.org.evil.com/" "https://wikipedia.org.evil.com/")"
rc="$(printf '%s\n' "${res}" | sed -n '1p')"
out="$(printf '%s\n' "${res}" | sed '1d')"
[[ "${rc}" == "40" ]] || die "expected rc=40 for suffix attack host (got ${rc})"
printf '%s\n' "${out}" | grep -q 'FAIL_NOT_ALLOWLISTED' || die "expected FAIL_NOT_ALLOWLISTED for suffix attack"
ok "suffix attack host remains blocked"

# Brand alias should not be implicitly trusted by category filter (texasinstruments.com != ti.com).
res="$(run_gate "https://ti.com/" "https://ti.com/")"
rc="$(printf '%s\n' "${res}" | sed -n '1p')"
out="$(printf '%s\n' "${res}" | sed '1d')"
[[ "${rc}" == "40" ]] || die "expected rc=40 for ti.com under filter containing only texasinstruments.com (got ${rc})"
printf '%s\n' "${out}" | grep -q 'FAIL_NOT_ALLOWLISTED' || die "expected FAIL_NOT_ALLOWLISTED for ti.com alias"
ok "brand alias blocked unless explicitly allowlisted in effective filter"

echo "PASS: test_fetch_gate_alias_behavior"
