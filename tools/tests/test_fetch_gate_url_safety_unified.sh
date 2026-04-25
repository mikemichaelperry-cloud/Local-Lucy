#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"
URL_SAFETY="${ROOT}/tools/internet/url_safety.py"
GATE="${ROOT}/tools/internet/run_fetch_with_gate.sh"

ok(){ echo "OK: $*"; }
die(){ echo "FAIL: $*" >&2; exit 1; }

[[ -f "${URL_SAFETY}" ]] || die "missing url_safety.py"
[[ -x "${GATE}" ]] || die "missing executable gate: ${GATE}"

cli_yes() {
  local u="$1"
  python3 "${URL_SAFETY}" validate-url "${u}" >/dev/null
}

cli_no() {
  local u="$1"
  if python3 "${URL_SAFETY}" validate-url "${u}" >/dev/null 2>&1; then
    die "url_safety unexpectedly allowed: ${u}"
  fi
}

cli_no "http://example.com/"
cli_no "https://127.0.0.1/"
cli_no "https://169.254.169.254/latest/meta-data/"
cli_no "https://[::1]/"
ok "url_safety CLI blocks local/meta/ip-literal inputs"

TMPD="$(mktemp -d)"
trap 'rm -rf "${TMPD}"' EXIT
FAKEBIN="${TMPD}/bin"
mkdir -p "${FAKEBIN}"
REAL_PYTHON3="$(command -v python3)"

cat > "${FAKEBIN}/curl" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
outfile=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -o)
      outfile="${2:-}"
      shift 2
      ;;
    --)
      shift
      break
      ;;
    *)
      shift
      ;;
  esac
done
: "${outfile:?missing -o outfile}"
printf 'fake body\n' > "${outfile}"
final="${FAKE_CURL_FINAL_URL:-https://reuters.com/}"
printf 'http_status=200 final_url=%s total_time_s=0.001 size_download=9 redirect_count=1 http_version=2\n' "${final}"
exit 0
SH
chmod +x "${FAKEBIN}/curl"

cat > "${FAKEBIN}/python3" <<SH
#!/usr/bin/env bash
set -euo pipefail
REAL_PYTHON3="${REAL_PYTHON3}"
if [[ "\${1:-}" == "${ROOT}/tools/internet/url_safety.py" && "\${2:-}" == "validate-url" ]]; then
  u="\${3:-}"
  case "\$u" in
    http://*) echo "ERR reason=https only"; exit 1 ;;
    *127.0.0.1*|*169.254.169.254*|*\\[::1\\]*)
      echo "ERR reason=forbidden"
      exit 1
      ;;
    *)
      echo "OK url=\$u host=example.com port=443"
      exit 0
      ;;
  esac
fi
exec "\$REAL_PYTHON3" "\$@"
SH
chmod +x "${FAKEBIN}/python3"

# Simulate redirect escape to localhost; unified URL safety should reject final URL with FAIL_POLICY.
set +e
gate_out="$(
  PATH="${FAKEBIN}:$PATH" \
  FAKE_CURL_FINAL_URL="http://127.0.0.1:8080/" \
  "${GATE}" "https://reuters.com/" 2>&1
)"
gate_rc=$?
set -e
[[ "${gate_rc}" == "41" ]] || die "expected gate rc=41 for unsafe final redirect (got ${gate_rc})"
printf '%s\n' "${gate_out}" | grep -q 'reason=FAIL_POLICY' || die "expected FAIL_POLICY in FETCH_META for unsafe final redirect"
ok "fetch gate uses unified URL safety for final redirect URL"

echo "PASS: test_fetch_gate_url_safety_unified"
