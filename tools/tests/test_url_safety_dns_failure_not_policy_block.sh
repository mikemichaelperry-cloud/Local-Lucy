#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"
MOD_PATH="${ROOT}/tools/internet/url_safety.py"

ok(){ echo "OK: $*"; }
die(){ echo "FAIL: $*" >&2; exit 1; }

[[ -f "${MOD_PATH}" ]] || die "missing module: ${MOD_PATH}"

python3 - <<'PY' "${MOD_PATH}"
import importlib.util
import socket
import sys

mod_path = sys.argv[1]
spec = importlib.util.spec_from_file_location("url_safety_mod", mod_path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

orig_getaddrinfo = mod.socket.getaddrinfo
try:
    def flaky_getaddrinfo(host, *args, **kwargs):
        if host == "example.com":
            raise socket.gaierror("temporary failure")
        return orig_getaddrinfo(host, *args, **kwargs)
    mod.socket.getaddrinfo = flaky_getaddrinfo

    _, host, port, reason = mod.parse_and_validate_url("https://example.com/")
    assert reason is None, reason
    assert host == "example.com"
    assert port == 443

    _, _, _, reason = mod.parse_and_validate_url("https://127.0.0.1/")
    assert reason is not None and "forbidden" in reason

    _, _, _, reason = mod.parse_and_validate_url("https://localhost/")
    assert reason is not None and "localhost" in reason
finally:
    mod.socket.getaddrinfo = orig_getaddrinfo
PY

ok "url_safety allows public host on DNS failure but still blocks local targets"
echo "PASS: test_url_safety_dns_failure_not_policy_block"
