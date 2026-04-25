#!/usr/bin/env bash
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
TMPDIR_TEST="$(mktemp -d)"
trap 'rm -rf "${TMPDIR_TEST}"' EXIT

die() {
  echo "FAIL: $*" >&2
  exit 1
}

FAKE_ROOT="${TMPDIR_TEST}/root"
mkdir -p "${TMPDIR_TEST}/bin" "${FAKE_ROOT}/tools/internet" "${FAKE_ROOT}/config/trust/generated"

cp "${ROOT}/tools/internet/run_fetch_with_gate.sh" "${FAKE_ROOT}/tools/internet/run_fetch_with_gate.sh"
chmod +x "${FAKE_ROOT}/tools/internet/run_fetch_with_gate.sh"

cat > "${FAKE_ROOT}/tools/internet/url_safety.py" <<'EOF'
#!/usr/bin/env python3
import sys
if len(sys.argv) >= 3 and sys.argv[1] == "validate-url":
    print("OK")
    raise SystemExit(0)
raise SystemExit(1)
EOF
chmod +x "${FAKE_ROOT}/tools/internet/url_safety.py"

cat > "${TMPDIR_TEST}/bin/curl" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
args=("$@")
outfile=""
url=""
compressed=0
for ((i=0; i<${#args[@]}; i++)); do
  case "${args[$i]}" in
    --compressed)
      compressed=1
      ;;
    -o)
      i=$((i+1))
      outfile="${args[$i]}"
      ;;
    http*)
      url="${args[$i]}"
      ;;
  esac
done

case "${url}" in
  https://ec.europa.eu/*)
    [[ "${compressed}" -eq 0 ]] || exit 91
    printf 'ec ok' > "${outfile}"
    printf 'http_status=200 final_url=%s total_time_s=0.1 size_download=5 redirect_count=0 http_version=1.1\n' "${url}"
    ;;
  https://www.bbc.com/*)
    [[ "${compressed}" -eq 1 ]] || exit 92
    printf 'bbc ok' > "${outfile}"
    printf 'http_status=200 final_url=%s total_time_s=0.1 size_download=6 redirect_count=0 http_version=2\n' "${url}"
    ;;
  *)
    exit 93
    ;;
esac
EOF
chmod +x "${TMPDIR_TEST}/bin/curl"

cat > "${FAKE_ROOT}/config/trust/generated/allowlist_fetch.txt" <<'EOF'
ec.europa.eu
bbc.com
EOF

PATH="${TMPDIR_TEST}/bin:${PATH}" \
  "${FAKE_ROOT}/tools/internet/run_fetch_with_gate.sh" "https://ec.europa.eu/commission/presscorner/api/rss?language=en" \
  > /dev/null 2> "${TMPDIR_TEST}/ec.err" || {
    cat "${TMPDIR_TEST}/ec.err" >&2
    die "ec.europa.eu fetch should succeed without --compressed"
  }

PATH="${TMPDIR_TEST}/bin:${PATH}" \
  "${FAKE_ROOT}/tools/internet/run_fetch_with_gate.sh" "https://www.bbc.com/news/technology" \
  > /dev/null 2> "${TMPDIR_TEST}/bbc.err" || {
    cat "${TMPDIR_TEST}/bbc.err" >&2
    die "bbc.com fetch should preserve --compressed"
  }

grep -q 'reason=OK' "${TMPDIR_TEST}/ec.err" || die "missing OK fetch meta for ec.europa.eu"
grep -q 'reason=OK' "${TMPDIR_TEST}/bbc.err" || die "missing OK fetch meta for bbc.com"

echo "PASS: europa fetch uses uncompressed path only for ec.europa.eu"
