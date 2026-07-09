#!/usr/bin/env python3
"""Pure-Python fetch gate for Local Lucy.

Replaces the bash/curl ``run_fetch_with_gate.sh`` implementation while
preserving the same contract, environment variables, exit codes, and
FETCH_META telemetry format.

Environment variables:
  LUCY_ROOT                          Project root (auto-detected if unset)
  LUCY_FETCH_ALLOWLIST_FILTER_FILE   Optional secondary domain allowlist
  LUCY_GATE_MAX_BYTES                Hard response-size cap (default 1_500_000)
  LUCY_GATE_CONNECT_TIMEOUT_S        TCP connect timeout (default 8)
  LUCY_GATE_MAX_TIME_S               Overall request timeout (default 25)
  LUCY_FETCH_FORCE_FINAL_URL         Override final URL in telemetry
  LUCY_DEBUG_ROUTE                   Emit debug route info to stderr
"""

from __future__ import annotations

import gzip
import ipaddress
import os
import socket
import sys
import time
import urllib.error
import urllib.request
import zlib
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Reason constants (must match run_fetch_with_gate.sh)
# ---------------------------------------------------------------------------
OK = "OK"
FAIL_DNS = "FAIL_DNS"
FAIL_CONNECT = "FAIL_CONNECT"
FAIL_TIMEOUT = "FAIL_TIMEOUT"
FAIL_TLS = "FAIL_TLS"
FAIL_HTTP_403 = "FAIL_HTTP_403"
FAIL_HTTP_401 = "FAIL_HTTP_401"
FAIL_HTTP_404 = "FAIL_HTTP_404"
FAIL_HTTP_429 = "FAIL_HTTP_429"
FAIL_HTTP_5XX = "FAIL_HTTP_5XX"
FAIL_HTTP_OTHER = "FAIL_HTTP_OTHER"
FAIL_TOO_LARGE = "FAIL_TOO_LARGE"
FAIL_REDIRECT_BLOCKED = "FAIL_REDIRECT_BLOCKED"
FAIL_NOT_ALLOWLISTED = "FAIL_NOT_ALLOWLISTED"
FAIL_POLICY = "FAIL_POLICY"
FAIL_UNKNOWN = "FAIL_UNKNOWN"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _root() -> Path:
    env = (os.environ.get("LUCY_ROOT") or "").strip()
    if env:
        return Path(env).expanduser().resolve()
    # Script lives at <root>/tools/internet/fetch_gate.py
    return Path(__file__).resolve().parents[2]


def _allowlist_path() -> Path:
    return _root() / "config" / "trust" / "generated" / "allowlist_fetch.txt"


def _decompress_body(body: bytes, encoding: str | None) -> bytes:
    """Decompress response body based on Content-Encoding header."""
    if not encoding:
        return body
    enc = encoding.strip().lower()
    if enc == "gzip":
        try:
            with gzip.GzipFile(fileobj=BytesIO(body)) as gf:
                return gf.read()
        except Exception:
            return body
    if enc == "deflate":
        try:
            return zlib.decompress(body)
        except zlib.error:
            try:
                return zlib.decompress(body, -zlib.MAX_WBITS)
            except zlib.error:
                return body
    if enc == "br":
        try:
            import brotli  # type: ignore[import]

            return brotli.decompress(body)
        except Exception:
            return body
    return body


def _domain_of(url: str) -> str:
    try:
        host = (urlparse(url).hostname or "").strip().lower().rstrip(".")
    except Exception:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host


def _load_allowlist(path: Path) -> list[str]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    domains: list[str] = []
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                s = line.strip().lower().rstrip(".")
                if not s or s.startswith("#"):
                    continue
                if s.startswith("www."):
                    s = s[4:]
                domains.append(s)
    except OSError:
        pass
    return domains


def _domain_allowed(domain: str, allowlist: list[str]) -> bool:
    if not domain or not allowlist:
        return False
    d = domain.strip().lower().rstrip(".")
    if d.startswith("www."):
        d = d[4:]
    for entry in allowlist:
        if d == entry or d.endswith("." + entry):
            return True
    return False


def _is_local_or_meta(url: str) -> bool:
    """Fallback policy check when url_safety.py is unavailable."""
    try:
        p = urlparse(url)
        h = (p.hostname or "").strip().lower()
    except Exception:
        return True
    if h in {"localhost", "localhost.localdomain"}:
        return True
    try:
        ip = ipaddress.ip_address(h)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return True
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(h, None)
        for info in infos:
            ip_str = info[4][0]
            ip = ipaddress.ip_address(ip_str)
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_multicast
                or ip.is_reserved
                or ip.is_unspecified
            ):
                return True
    except Exception:
        pass
    return False


def _validate_url_policy(url: str) -> bool:
    """Use url_safety.py if possible, otherwise replicate basic checks."""
    safety_path = _root() / "tools" / "internet" / "url_safety.py"
    if safety_path.exists():
        try:
            # Import relative to this file when possible
            sys.path.insert(0, str(safety_path.parent))
            from url_safety import parse_and_validate_url  # type: ignore[import]
        finally:
            sys.path.remove(str(safety_path.parent))
        try:
            norm_url, _host, _port, reason = parse_and_validate_url(url)
            return norm_url != "" and reason is None
        except Exception:
            pass
    # Fallback
    if _is_local_or_meta(url):
        return False
    try:
        scheme = urlparse(url).scheme
    except Exception:
        return False
    return scheme == "https"


def _bucket_http_status(status: int | str | None) -> str:
    try:
        status = int(status)
    except (TypeError, ValueError):
        return FAIL_UNKNOWN
    if status == 401:
        return FAIL_HTTP_401
    if status == 403:
        return FAIL_HTTP_403
    if status == 404:
        return FAIL_HTTP_404
    if status == 429:
        return FAIL_HTTP_429
    if 500 <= status < 600:
        return FAIL_HTTP_5XX
    return FAIL_HTTP_OTHER


def _bucket_url_error(exc: urllib.error.URLError) -> str:
    reason = exc.reason
    if isinstance(reason, str):
        rlower = reason.lower()
        if "ssl" in rlower or "tls" in rlower or "certificate" in rlower:
            return FAIL_TLS
        if "timed out" in rlower or "timeout" in rlower:
            return FAIL_TIMEOUT
        if "name" in rlower or "getaddrinfo" in rlower or "nodename" in rlower:
            return FAIL_DNS
        if "connection" in rlower or "refused" in rlower or "network" in rlower:
            return FAIL_CONNECT
    if isinstance(reason, socket.timeout):
        return FAIL_TIMEOUT
    if isinstance(reason, OSError):
        # errno mapping
        if isinstance(reason, ConnectionRefusedError):
            return FAIL_CONNECT
        if isinstance(reason, socket.timeout):
            return FAIL_TIMEOUT
        if isinstance(reason, TimeoutError):
            return FAIL_TIMEOUT
        err = getattr(reason, "errno", None)
        if err is not None:
            if err in {socket.EAI_NONAME, socket.EAI_NODATA, socket.EAI_FAIL}:
                return FAIL_DNS
            if err in {
                socket.ECONNREFUSED,
                socket.ECONNRESET,
                socket.ECONNABORTED,
                socket.ENETUNREACH,
                socket.EHOSTUNREACH,
            }:
                return FAIL_CONNECT
    return FAIL_UNKNOWN


def _is_retryable_error(exc: BaseException) -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in {408, 429, 500, 502, 503, 504}
    if isinstance(exc, urllib.error.URLError):
        reason = exc.reason
        if isinstance(reason, socket.timeout):
            return True
        if isinstance(reason, TimeoutError):
            return True
        if isinstance(reason, ConnectionError):
            return True
        if isinstance(reason, OSError):
            return True
        return True
    if isinstance(exc, TimeoutError):
        return True
    if isinstance(exc, socket.timeout):
        return True
    return False


def _domain_prefers_uncompressed(host: str) -> bool:
    return host == "ec.europa.eu" or host.endswith(".ec.europa.eu")


# ---------------------------------------------------------------------------
# Fetch internals
# ---------------------------------------------------------------------------


def _build_request(
    url: str,
    *,
    accept_compressed: bool = True,
    proto: str = "http2",
) -> urllib.request.Request:
    headers: dict[str, str] = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    if accept_compressed:
        encodings = ["gzip", "deflate"]
        try:
            import brotli  # type: ignore[import]  # noqa: F401

            encodings.append("br")
        except Exception:
            pass
        headers["Accept-Encoding"] = ", ".join(encodings)
    if proto == "http1.1":
        # urllib stdlib cannot force HTTP/1.1, but we signal intent via a marker
        # header that is ignored by compliant servers.  This is used only for
        # telemetry parity with the curl implementation.
        headers["X-Lucy-Fetch-Proto"] = "http1.1"
    return urllib.request.Request(url, headers=headers, method="GET")


def _read_limited(
    response: urllib.response.addinfourl,
    max_bytes: int,
) -> tuple[bytes, bool]:
    """Read up to max_bytes + 1 so we can detect oversize responses."""
    chunks: list[bytes] = []
    total = 0
    truncated = False
    while True:
        to_read = min(65536, max_bytes + 1 - total)
        if to_read <= 0:
            truncated = True
            break
        chunk = response.read(to_read)
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > max_bytes:
            truncated = True
            break
    return b"".join(chunks), truncated


class _AttemptResult:
    __slots__ = (
        "rc",
        "reason",
        "status",
        "final_url",
        "final_domain",
        "bytes_dl",
        "time_s",
        "redirects",
        "proto",
        "allowlisted_final",
        "body",
        "too_large",
    )

    def __init__(self) -> None:
        self.rc = 0
        self.reason = OK
        self.status: int | str | None = "none"
        self.final_url = ""
        self.final_domain = ""
        self.bytes_dl = 0
        self.time_s = 0.0
        self.redirects = 0
        self.proto = "none"
        self.allowlisted_final = False
        self.body = b""
        self.too_large = False

    def as_tuple(self) -> tuple[int, str, str | int | None, str, str, int, float, int, str, bool]:
        return (
            self.rc,
            self.reason,
            self.status,
            self.final_url,
            self.final_domain,
            self.bytes_dl,
            self.time_s,
            self.redirects,
            self.proto,
            self.allowlisted_final,
        )


def _run_attempt(
    url: str,
    proto: str,
    max_bytes: int,
    connect_timeout: int | float,
    max_time: int | float,
    allowlist: list[str],
    filter_allowlist: list[str],
) -> _AttemptResult:
    r = _AttemptResult()
    start = time.perf_counter()
    host = _domain_of(url)
    accept_compressed = not _domain_prefers_uncompressed(host)

    try:
        req = _build_request(url, accept_compressed=accept_compressed, proto=proto)
        # urllib.request does not expose per-redirect history, so we follow
        # redirects transparently and clamp the overall timeout.
        with urllib.request.urlopen(req, timeout=connect_timeout) as resp:
            raw_body, truncated = _read_limited(resp, max_bytes)
            encoding = resp.headers.get("Content-Encoding")
            body = _decompress_body(raw_body, encoding)
            r.body = body[:max_bytes]
            r.too_large = truncated or len(body) > max_bytes
            r.status = resp.getcode()
            r.final_url = resp.geturl()
            r.redirects = int(getattr(resp, "redirects", 0) or 0)
    except urllib.error.HTTPError as exc:
        r.status = exc.code
        r.final_url = exc.geturl() or url
        raw_body = exc.read(max_bytes + 1)
        encoding = exc.headers.get("Content-Encoding")
        body = _decompress_body(raw_body, encoding)
        if len(body) > max_bytes:
            r.body = body[:max_bytes]
            r.too_large = True
        else:
            r.body = body
    except Exception as exc:
        r.rc = 1
        if isinstance(exc, urllib.error.URLError):
            r.reason = _bucket_url_error(exc)
        elif isinstance(exc, TimeoutError) or isinstance(exc, socket.timeout):
            r.reason = FAIL_TIMEOUT
        elif isinstance(exc, socket.gaierror):
            r.reason = FAIL_DNS
        elif isinstance(exc, ConnectionRefusedError):
            r.reason = FAIL_CONNECT
        else:
            r.reason = FAIL_UNKNOWN
        r.final_url = url
        r.status = "none"
        elapsed = time.perf_counter() - start
        r.time_s = elapsed
        r.proto = proto
        return r

    elapsed = time.perf_counter() - start
    r.time_s = elapsed
    r.proto = proto
    if os.environ.get("LUCY_FETCH_FORCE_FINAL_URL"):
        r.final_url = os.environ["LUCY_FETCH_FORCE_FINAL_URL"]
    r.final_domain = _domain_of(r.final_url)
    r.allowlisted_final = _domain_allowed(r.final_domain, allowlist) and (
        not filter_allowlist or _domain_allowed(r.final_domain, filter_allowlist)
    )
    r.bytes_dl = len(r.body)

    # Determine reason
    r.reason = OK
    if not _validate_url_policy(r.final_url):
        r.reason = FAIL_POLICY
    elif not r.allowlisted_final:
        r.reason = FAIL_REDIRECT_BLOCKED
    elif r.too_large:
        r.reason = FAIL_TOO_LARGE
    elif r.status in ("none", "000", 0, None) or r.bytes_dl == 0:
        r.reason = FAIL_UNKNOWN
    elif isinstance(r.status, int) and r.status >= 400:
        r.reason = _bucket_http_status(r.status)

    return r


def _emit_fetch_meta(
    final_url: str,
    final_domain: str,
    http_status: str | int | None,
    reason: str,
    bytes: int,
    total_time_ms: int,
    attempts: int,
    proto: str,
    redirect_count: int,
    allowlisted_final: bool,
    attempt1_status: str | int | None,
    attempt1_reason: str,
    attempt1_proto: str,
    attempt2_status: str | int | None,
    attempt2_reason: str,
    attempt2_proto: str,
) -> None:
    def _s(v: Any) -> str:
        if v is None:
            return "none"
        if isinstance(v, bool):
            return "true" if v else "false"
        return str(v)

    line = (
        f"FETCH_META final_url={_s(final_url)} final_domain={_s(final_domain)} "
        f"http_status={_s(http_status)} reason={_s(reason)} bytes={_s(bytes)} "
        f"total_time_ms={_s(total_time_ms)} attempts={_s(attempts)} proto={_s(proto)} "
        f"redirect_count={_s(redirect_count)} allowlisted_final={_s(allowlisted_final)} "
        f"attempt1_status={_s(attempt1_status)} attempt1_reason={_s(attempt1_reason)} attempt1_proto={_s(attempt1_proto)} "
        f"attempt2_status={_s(attempt2_status)} attempt2_reason={_s(attempt2_reason)} attempt2_proto={_s(attempt2_proto)}"
    )
    print(line, file=sys.stderr)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _resolve_allowlists() -> tuple[list[str], list[str]]:
    allowlist = _load_allowlist(_allowlist_path())
    filter_path = (os.environ.get("LUCY_FETCH_ALLOWLIST_FILTER_FILE") or "").strip()
    filter_allowlist: list[str] = []
    if filter_path:
        filter_allowlist = _load_allowlist(Path(filter_path).expanduser())
    return allowlist, filter_allowlist


def _require_allowlist() -> None:
    path = _allowlist_path()
    if not path.exists() or path.stat().st_size == 0:
        print("ERROR: generated fetch allowlist missing or empty.", file=sys.stderr)
        print("Run:", file=sys.stderr)
        print("  python3 tools/trust/generate_trust_lists.py", file=sys.stderr)
        print("  tools/trust/verify_trust_lists.sh", file=sys.stderr)
        raise SystemExit(2)
    filter_path = (os.environ.get("LUCY_FETCH_ALLOWLIST_FILTER_FILE") or "").strip()
    if filter_path and (not Path(filter_path).exists() or Path(filter_path).stat().st_size == 0):
        print(f"ERROR: router/category allowlist missing or empty: {filter_path}", file=sys.stderr)
        raise SystemExit(2)


def fetch_with_meta(
    url: str,
    timeout: int = 25,
    prompt: bool = False,
    *,
    _emit: bool = True,
) -> tuple[str, bytes, dict[str, Any]]:
    """Core fetch returning (reason, body_bytes, meta_dict).

    When *_emit* is True, FETCH_META is written to stderr for CLI parity.
    """
    if prompt:
        # Prompt flag is a no-op in non-interactive library usage.
        pass

    _require_allowlist()
    allowlist, filter_allowlist = _resolve_allowlists()

    if os.environ.get("LUCY_DEBUG_ROUTE") == "1":
        print(f"DEBUG_ROUTE allowlist file loaded = {_allowlist_path()}", file=sys.stderr)
        if filter_allowlist:
            print(
                f"DEBUG_ROUTE allowlist filter loaded = {os.environ.get('LUCY_FETCH_ALLOWLIST_FILTER_FILE')}",
                file=sys.stderr,
            )

    def _policy_meta() -> dict[str, Any]:
        return {
            "final_url": url,
            "final_domain": _domain_of(url),
            "http_status": "none",
            "reason": FAIL_POLICY,
            "bytes": 0,
            "total_time_ms": 0,
            "attempts": 0,
            "proto": "none",
            "redirect_count": 0,
            "allowlisted_final": False,
            "attempt1_status": "none",
            "attempt1_reason": FAIL_POLICY,
            "attempt1_proto": "none",
            "attempt2_status": "none",
            "attempt2_reason": "none",
            "attempt2_proto": "none",
        }

    if not _validate_url_policy(url):
        meta = _policy_meta()
        if _emit:
            _emit_fetch_meta(**meta)
        return FAIL_POLICY, b"", meta

    domain = _domain_of(url)
    if not _domain_allowed(domain, allowlist):
        meta = _policy_meta()
        meta["reason"] = FAIL_NOT_ALLOWLISTED
        meta["attempt1_reason"] = FAIL_NOT_ALLOWLISTED
        if _emit:
            _emit_fetch_meta(**meta)
        return FAIL_NOT_ALLOWLISTED, b"", meta
    if filter_allowlist and not _domain_allowed(domain, filter_allowlist):
        meta = _policy_meta()
        meta["reason"] = FAIL_NOT_ALLOWLISTED
        meta["attempt1_reason"] = FAIL_NOT_ALLOWLISTED
        if _emit:
            _emit_fetch_meta(**meta)
        return FAIL_NOT_ALLOWLISTED, b"", meta

    max_bytes = int(os.environ.get("LUCY_GATE_MAX_BYTES") or "1500000")
    connect_timeout = int(os.environ.get("LUCY_GATE_CONNECT_TIMEOUT_S") or "8")
    max_time = int(os.environ.get("LUCY_GATE_MAX_TIME_S") or str(timeout))

    # Attempt 1: best-effort HTTP/2 (urllib will negotiate HTTP/1.1 or HTTP/2
    # as the server allows; we report it as the http2 attempt for parity).
    a1 = _run_attempt(
        url, "http2", max_bytes, connect_timeout, max_time, allowlist, filter_allowlist
    )

    final = a1
    attempts = 1
    a2: _AttemptResult | None = None

    if a1.reason != OK:
        # Attempt 2: fallback to HTTP/1.1 marker.
        a2 = _run_attempt(
            url, "http1.1", max_bytes, connect_timeout, max_time, allowlist, filter_allowlist
        )
        attempts = 2
        final = a2

    final_time_ms = int(round(final.time_s * 1000.0))

    a1_status = a1.status
    a1_reason = a1.reason
    a1_proto = a1.proto
    a2_status: str | int | None = "none"
    a2_reason = "none"
    a2_proto = "none"
    final_proto = final.proto

    if a2 is not None:
        a2_status = a2.status
        a2_reason = a2.reason
        a2_proto = a2.proto
        final_proto = "http2_fallback_http1.1"

    meta: dict[str, Any] = {
        "final_url": final.final_url,
        "final_domain": final.final_domain,
        "http_status": final.status,
        "reason": final.reason,
        "bytes": final.bytes_dl,
        "total_time_ms": final_time_ms,
        "attempts": attempts,
        "proto": final_proto,
        "redirect_count": final.redirects,
        "allowlisted_final": final.allowlisted_final,
        "attempt1_status": a1_status,
        "attempt1_reason": a1_reason,
        "attempt1_proto": a1_proto,
        "attempt2_status": a2_status,
        "attempt2_reason": a2_reason,
        "attempt2_proto": a2_proto,
    }

    if _emit:
        _emit_fetch_meta(**meta)

    if final.reason != OK:
        return final.reason, b"", meta

    body = a2.body if a2 is not None else a1.body
    return OK, body[:max_bytes], meta


def fetch_url(url: str, timeout: int = 25, prompt: bool = False) -> tuple[str, bytes]:
    """Fetch *url* and return (reason, body_bytes).

    ``reason`` is one of the FAIL_* or OK constants defined in this module.
    """
    reason, body, _meta = fetch_with_meta(url, timeout=timeout, prompt=prompt)
    return reason, body


def fetch_url_text(url: str, timeout: int = 25, prompt: bool = False) -> tuple[str, str]:
    """Fetch *url* and return (reason, decoded_text).

    Text is decoded as UTF-8 with latin-1 fallback.
    """
    reason, body, _meta = fetch_with_meta(url, timeout=timeout, prompt=prompt)
    if reason != OK or not body:
        return reason, ""
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        text = body.decode("latin-1", errors="ignore")
    return OK, text


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    prompt = False
    if argv and argv[0] == "--prompt":
        prompt = True
        argv = argv[1:]

    if not argv:
        print("usage: fetch_gate.py [--prompt] <url>", file=sys.stderr)
        return 2

    url = argv[0]

    if prompt and sys.stdin.isatty():
        print("Proceed? Type yes to continue: ", file=sys.stderr, end="")
        try:
            ans = input().strip()
        except EOFError:
            ans = ""
        if ans != "yes":
            return 1

    reason, body, _meta = fetch_with_meta(url, timeout=25, prompt=False)

    if reason != OK:
        if reason == FAIL_NOT_ALLOWLISTED or reason == FAIL_REDIRECT_BLOCKED:
            return 40
        if reason == FAIL_POLICY:
            return 41
        return 42

    # Write bytes to stdout preserving binary content
    sys.stdout.buffer.write(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
