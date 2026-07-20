#!/usr/bin/env bash
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
GATE="${ROOT}/tools/internet/fetch_gate.py"

die() {
  echo "FAIL: $*" >&2
  exit 1
}

TMPDIR_TEST="$(mktemp -d)"
trap 'rm -rf "${TMPDIR_TEST}"' EXIT

ALLOWLIST="${TMPDIR_TEST}/allowlist_fetch.txt"
printf 'ec.europa.eu\nbbc.com\n' > "${ALLOWLIST}"

python3 - <<'PY' "${GATE}" "${ALLOWLIST}"
import sys
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
        self.redirects = 0

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


captured: list[fg.urllib.request.Request] = []

def fake_urlopen(req, timeout=None):
    captured.append(req)
    return FakeResp(req.get_full_url(), 200)


fg.urllib.request.urlopen = fake_urlopen
fg._allowlist_path = lambda: allowlist_path


def accept_encoding(url: str) -> str | None:
    captured.clear()
    reason, _body, _meta = fg.fetch_with_meta(url, _emit=False)
    if reason != fg.OK:
        raise AssertionError(f"fetch unexpectedly failed for {url}: {reason}")
    if len(captured) != 1:
        raise AssertionError(f"expected exactly one request for {url}, got {len(captured)}")
    return captured[0].headers.get("Accept-encoding")


ec_encoding = accept_encoding("https://ec.europa.eu/commission/presscorner/api/rss?language=en")
if ec_encoding:
    raise AssertionError(f"ec.europa.eu fetch should be uncompressed, got Accept-Encoding: {ec_encoding}")

bbc_encoding = accept_encoding("https://www.bbc.com/news/technology")
if not bbc_encoding or "gzip" not in bbc_encoding:
    raise AssertionError(f"bbc.com fetch should use compression, got Accept-Encoding: {bbc_encoding}")
PY

echo "PASS: europa fetch uses uncompressed path only for ec.europa.eu"
