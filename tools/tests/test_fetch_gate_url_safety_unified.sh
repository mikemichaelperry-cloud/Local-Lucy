#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"
URL_SAFETY="${ROOT}/tools/internet/url_safety.py"
GATE="${ROOT}/tools/internet/fetch_gate.py"

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
ALLOWLIST="${TMPD}/allowlist_fetch.txt"
printf 'example.com\n' > "${ALLOWLIST}"

python3 - <<'PY' "${GATE}" "${ALLOWLIST}"
import os
import sys
from io import StringIO
from pathlib import Path

gate_path = Path(sys.argv[1])
allowlist_path = Path(sys.argv[2])
sys.path.insert(0, str(gate_path.parent))
import fetch_gate as fg


class FakeResp:
    def __init__(self, url: str, code: int, body: bytes = b"ok") -> None:
        self._url = url
        self._code = code
        self._body = body
        self._offset = 0
        self.headers = {}
        self.redirects = 1

    def getcode(self) -> int:
        return self._code

    def geturl(self) -> str:
        return self._url

    def read(self, n: int = -1) -> bytes:
        if n < 0 or n > len(self._body) - self._offset:
            n = len(self._body) - self._offset
        chunk = self._body[self._offset : self._offset + n]
        self._offset += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def fake_urlopen(req, timeout=None):
    return FakeResp("https://example.com/", 200)


fg.urllib.request.urlopen = fake_urlopen
fg._allowlist_path = lambda: allowlist_path
os.environ["LUCY_FETCH_FORCE_FINAL_URL"] = "http://127.0.0.1:8080/"

old_stderr = sys.stderr
sys.stderr = StringIO()
try:
    rc = fg.main(["https://example.com/"])
finally:
    captured = sys.stderr.getvalue()
    sys.stderr = old_stderr

if rc != 41:
    raise AssertionError(f"expected gate rc=41 for unsafe final redirect (got {rc})")
if "reason=FAIL_POLICY" not in captured:
    raise AssertionError(f"expected FAIL_POLICY in FETCH_META for unsafe final redirect: {captured}")
PY

ok "fetch gate uses unified URL safety for final redirect URL"

echo "PASS: test_fetch_gate_url_safety_unified"
