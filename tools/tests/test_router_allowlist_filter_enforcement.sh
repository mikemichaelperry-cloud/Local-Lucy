#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"
GATE="${ROOT}/tools/internet/run_fetch_with_gate.sh"
MEDICAL_ALLOWLIST="${ROOT}/config/trust/generated/medical.txt"

ok(){ echo "OK: $*"; }
die(){ echo "FAIL: $*" >&2; exit 1; }

[[ -x "${GATE}" ]] || die "missing executable: ${GATE}"
[[ -s "${MEDICAL_ALLOWLIST}" ]] || die "missing allowlist: ${MEDICAL_ALLOWLIST}"

TMPD="$(mktemp -d)"
trap 'rm -rf "${TMPD}"' EXIT
FAKEBIN="${TMPD}/bin"
mkdir -p "${FAKEBIN}"
REAL_PYTHON3="$(command -v python3)"

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
  local out rc
  set +e
  out="$(
    PATH="${FAKEBIN}:$PATH" \
    LUCY_FETCH_ALLOWLIST_FILTER_FILE="${MEDICAL_ALLOWLIST}" \
    "${GATE}" "${url}" 2>&1
  )"
  rc=$?
  set -e
  printf '%s\n' "${rc}"
  printf '%s\n' "${out}"
}

# Base-tier allowlisted news domain should be blocked by medical category filter.
res="$(run_gate "https://reuters.com/")"
rc="$(printf '%s\n' "${res}" | sed -n '1p')"
out="$(printf '%s\n' "${res}" | sed '1d')"
[[ "${rc}" == "40" ]] || die "expected rc=40 for reuters.com under medical filter (got ${rc})"
printf '%s\n' "${out}" | grep -q 'FAIL_NOT_ALLOWLISTED' || die "expected FAIL_NOT_ALLOWLISTED for reuters.com"
ok "medical router filter blocks non-medical tier12 domain"

# Medical-allowlisted domain should pass allowlist checks (may still fail later due DNS/network in sandbox).
res="$(run_gate "https://pubmed.ncbi.nlm.nih.gov/")"
rc="$(printf '%s\n' "${res}" | sed -n '1p')"
out="$(printf '%s\n' "${res}" | sed '1d')"
printf '%s\n' "${out}" | grep -q 'final_domain=pubmed.ncbi.nlm.nih.gov' || die "expected pubmed final domain in FETCH_META"
printf '%s\n' "${out}" | grep -q 'allowlisted_final=true' || die "expected allowlisted_final=true for pubmed under medical filter"
if printf '%s\n' "${out}" | grep -q 'FAIL_NOT_ALLOWLISTED'; then
  die "pubmed unexpectedly blocked by allowlist filter"
fi
ok "medical router filter permits medical-listed domain (allowlist stage)"

echo "PASS: test_router_allowlist_filter_enforcement"
