#!/usr/bin/env python3
"""Comprehensive trust-site probe for the active Local Lucy snapshot."""

from __future__ import annotations

import concurrent.futures
import datetime as dt
import json
import os
import socket
import ssl
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, Tuple

OK = "OK"
FAIL_DNS = "FAIL_DNS"
FAIL_CONNECT = "FAIL_CONNECT"
FAIL_TLS = "FAIL_TLS"
FAIL_TIMEOUT = "FAIL_TIMEOUT"
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

EXPECT_MODES = {"strict", "reachable", "connect_only"}


def fail(msg: str) -> None:
    print(f"ERR: {msg}", file=sys.stderr)
    raise SystemExit(1)


def detect_root() -> str:
    env_root = os.environ.get("LUCY_ROOT", "").strip()
    if env_root:
        root = env_root
        if not os.path.isdir(root):
            fail(f"LUCY_ROOT does not exist: {root}")
        if not (
            os.path.isfile(os.path.join(root, "lucy_chat.sh"))
            or os.path.isdir(os.path.join(root, "tools"))
            or os.path.isdir(os.path.join(root, "snapshots"))
        ):
            fail(f"LUCY_ROOT failed marker check: {root}")
        return root
    script_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    if (
        os.path.isdir(script_root)
        and (
            os.path.isfile(os.path.join(script_root, "lucy_chat.sh"))
            or os.path.isdir(os.path.join(script_root, "tools"))
            or os.path.isdir(os.path.join(script_root, "snapshots"))
        )
    ):
        return script_root
    home = os.path.expanduser("~")
    fallback = os.path.join(home, "lucy")
    if os.path.isdir(fallback):
        root = fallback
    else:
        fail("could not determine ROOT")
    if not (
        os.path.isfile(os.path.join(root, "lucy_chat.sh"))
        or os.path.isdir(os.path.join(root, "tools"))
        or os.path.isdir(os.path.join(root, "snapshots"))
    ):
        fail(f"ROOT failed marker check: {root}")
    return root


def _parse_scalar(raw: str):
    s = raw.strip()
    if not s:
        return ""
    if s.startswith('"') and s.endswith('"'):
        return s[1:-1]
    if s in ("true", "false"):
        return s == "true"
    if s.isdigit():
        return int(s)
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        if not inner:
            return []
        vals = []
        for p in inner.split(","):
            v = p.strip()
            if v.startswith('"') and v.endswith('"'):
                v = v[1:-1]
            vals.append(v)
        return vals
    return s


def load_policy(path: str) -> Dict:
    data: Dict[str, object] = {}
    current_list_key = None
    with open(path, "r", encoding="utf-8") as f:
        for lineno, raw in enumerate(f, 1):
            line = raw.rstrip("\n")
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            indent = len(line) - len(line.lstrip(" "))
            if current_list_key and indent >= 2 and s.startswith("- "):
                item = _parse_scalar(s[1:].strip())
                existing = data.get(current_list_key)
                if not isinstance(existing, list):
                    fail(f"{path}:{lineno}: internal parser error for list key {current_list_key}")
                existing.append(item)
                continue
            if current_list_key and (indent >= 2 or s.startswith("- ")):
                fail(f"{path}:{lineno}: unsupported nested policy YAML shape")
            current_list_key = None
            if ":" not in s:
                fail(f"{path}:{lineno}: invalid policy line")
            k, v = s.split(":", 1)
            key = k.strip()
            if not v.strip():
                data[key] = []
                current_list_key = key
                continue
            data[key] = _parse_scalar(v)
    if data.get("version") != 1:
        fail("policy version must be 1")
    tiers = data.get("fetch_allow_tiers")
    if not isinstance(tiers, list) or not tiers:
        fail("policy fetch_allow_tiers must be a non-empty list")
    return {"fetch_allow_tiers": [int(x) for x in tiers]}


def load_catalog_metadata(path: str) -> Dict[str, Dict]:
    version = None
    in_domains = False
    current = None
    meta: Dict[str, Dict] = {}

    with open(path, "r", encoding="utf-8") as f:
        for lineno, raw in enumerate(f, 1):
            line = raw.rstrip("\n")
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            indent = len(line) - len(line.lstrip(" "))

            if indent == 0 and s.startswith("version:"):
                version = _parse_scalar(s.split(":", 1)[1])
                continue
            if indent == 0 and s == "domains:":
                in_domains = True
                continue
            if not in_domains:
                fail(f"{path}:{lineno}: unexpected content before domains")

            if indent == 2 and s.endswith(":"):
                current = s[:-1].strip()
                meta[current] = {}
                continue
            if indent == 4 and ":" in s and current:
                k, v = s.split(":", 1)
                meta[current][k.strip()] = _parse_scalar(v)
                continue

            fail(f"{path}:{lineno}: unsupported YAML shape")

    if version != 1:
        fail("catalog version must be 1")
    return meta


def load_generated_domains(path: str) -> List[str]:
    out: List[str] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if s and not s.startswith("#"):
                out.append(s)
    return sorted(set(out))


def host_in_allowlist(host: str, allowset: set[str]) -> bool:
    if host in allowset:
        return True
    for d in allowset:
        if host.endswith("." + d):
            return True
    return False


def canonical_catalog_domain(domain: str, meta: Dict[str, Dict]) -> str:
    d = (domain or "").strip().lower()
    if d in meta:
        return d
    if d.startswith("www.") and d[4:] in meta:
        return d[4:]
    return d


def bucket_http_status(status: int) -> str:
    if status == 401:
        return FAIL_HTTP_401
    if status == 403:
        return FAIL_HTTP_403
    if status == 404:
        return FAIL_HTTP_404
    if status == 429:
        return FAIL_HTTP_429
    if 500 <= status <= 599:
        return FAIL_HTTP_5XX
    return FAIL_HTTP_OTHER


def bucket_from_exc(err: str) -> str:
    s = (err or "").lower()
    if "name resolution" in s or "nodename nor servname" in s or "no address associated" in s:
        return FAIL_DNS
    if "timed out" in s or "timeout" in s:
        return FAIL_TIMEOUT
    if "certificate" in s or "ssl" in s or "tls" in s:
        return FAIL_TLS
    if "connection refused" in s or "network is unreachable" in s or "failed to connect" in s:
        return FAIL_CONNECT
    return FAIL_UNKNOWN


def dns_probe(domain: str) -> Tuple[bool, List[str], str, str]:
    try:
        infos = socket.getaddrinfo(domain, 443)
    except Exception as e:
        return False, [], str(e), FAIL_DNS
    addrs = sorted({i[4][0] for i in infos})
    return True, addrs, "", OK


def tcp_probe(domain: str, timeout_s: float = 4.0) -> Tuple[bool, str, str]:
    try:
        with socket.create_connection((domain, 443), timeout=timeout_s):
            return True, "", OK
    except Exception as e:
        err = str(e)
        return False, err, bucket_from_exc(err)


def http_probe(domain: str, probe_paths: List[str]) -> Dict[str, str]:
    paths = probe_paths if probe_paths else ["/"]
    last = {
        "response_received": "false",
        "tls_ok": "false",
        "status": "",
        "final_url": f"https://{domain}/",
        "final_host": "",
        "content_type": "",
        "error": "no_probe_attempt",
        "reason_bucket": FAIL_UNKNOWN,
        "probe_path": "/",
    }

    for p in paths:
        path = p if p.startswith("/") else "/"
        url = f"https://{domain}{path}"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "LocalLucy-TrustProbe/1.0",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=12) as resp:
                final_url = resp.geturl()
                final_host = urllib.parse.urlparse(final_url).hostname or ""
                status = int(getattr(resp, "status", 200))
                ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                try:
                    _ = resp.read(1024)
                except Exception:
                    pass
                reason = OK
                if status >= 400:
                    reason = bucket_http_status(status)
                return {
                    "response_received": "true",
                    "tls_ok": "true",
                    "status": str(status),
                    "final_url": final_url,
                    "final_host": final_host.lower(),
                    "content_type": ctype,
                    "error": "",
                    "reason_bucket": reason,
                    "probe_path": path,
                }
        except urllib.error.HTTPError as e:
            final_url = e.geturl() if hasattr(e, "geturl") else url
            final_host = urllib.parse.urlparse(final_url).hostname or ""
            code = int(getattr(e, "code", 0))
            ctype = ""
            try:
                ctype = (e.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            except Exception:
                ctype = ""
            try:
                _ = e.read(1024)
            except Exception:
                pass
            return {
                "response_received": "true",
                "tls_ok": "true",
                "status": str(code),
                "final_url": final_url,
                "final_host": final_host.lower(),
                "content_type": ctype,
                "error": f"http_error:{code}",
                "reason_bucket": bucket_http_status(code),
                "probe_path": path,
            }
        except ssl.SSLError as e:
            last = {
                "response_received": "false",
                "tls_ok": "false",
                "status": "",
                "final_url": url,
                "final_host": "",
                "content_type": "",
                "error": str(e),
                "reason_bucket": FAIL_TLS,
                "probe_path": path,
            }
        except Exception as e:
            err = str(e)
            last = {
                "response_received": "false",
                "tls_ok": "false",
                "status": "",
                "final_url": url,
                "final_host": "",
                "content_type": "",
                "error": err,
                "reason_bucket": bucket_from_exc(err),
                "probe_path": path,
            }
    return last


def gate_probe(root: str, domain: str, probe_paths: List[str]) -> Dict[str, str]:
    path = probe_paths[0] if probe_paths else "/"
    url = f"https://{domain}{path}"
    cmd = [os.path.join(root, "tools", "internet", "run_fetch_with_gate.sh"), url]
    timeout_seen = False
    for _ in range(2):
        try:
            proc = subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                timeout=25,
            )
            stderr = (proc.stderr or "").strip()
            meta = {
                "reason": "",
                "http_status": "none",
                "final_url": "",
                "final_domain": "",
                "attempts": "",
                "proto": "",
                "allowlisted_final": "",
            }
            for line in stderr.splitlines():
                if line.startswith("FETCH_META "):
                    parts = line.split()
                    for part in parts[1:]:
                        if "=" not in part:
                            continue
                        k, v = part.split("=", 1)
                        if k in meta:
                            meta[k] = v
            if proc.returncode == 40:
                status = "blocked_allowlist"
            elif proc.returncode in (0, 22, 42):
                status = "allowed_by_gate"
            else:
                status = "other_error"
            return {
                "rc": str(proc.returncode),
                "status": status,
                "stderr": stderr[:500],
                "probe_path": path,
                "reason_bucket": meta["reason"] or FAIL_UNKNOWN,
                "meta_http_status": meta["http_status"] or "none",
                "meta_final_url": meta["final_url"],
                "meta_final_domain": meta["final_domain"],
                "meta_attempts": meta["attempts"],
                "meta_proto": meta["proto"],
                "meta_allowlisted_final": meta["allowlisted_final"],
            }
        except subprocess.TimeoutExpired:
            timeout_seen = True
            continue
        except Exception as e:
            return {
                "rc": "1",
                "status": "other_error",
                "stderr": str(e),
                "probe_path": path,
                "reason_bucket": FAIL_UNKNOWN,
                "meta_http_status": "none",
                "meta_final_url": "",
                "meta_final_domain": "",
                "meta_attempts": "",
                "meta_proto": "",
                "meta_allowlisted_final": "",
            }
    if timeout_seen:
        return {
            "rc": "124",
            "status": "timeout",
            "stderr": "timeout",
            "probe_path": path,
            "reason_bucket": FAIL_TIMEOUT,
            "meta_http_status": "none",
            "meta_final_url": "",
            "meta_final_domain": "",
            "meta_attempts": "",
            "meta_proto": "",
            "meta_allowlisted_final": "",
        }
    return {
        "rc": "1",
        "status": "other_error",
        "stderr": "unknown",
        "probe_path": path,
        "reason_bucket": FAIL_UNKNOWN,
        "meta_http_status": "none",
        "meta_final_url": "",
        "meta_final_domain": "",
        "meta_attempts": "",
        "meta_proto": "",
        "meta_allowlisted_final": "",
    }


def expectation_mode(meta: Dict[str, object]) -> str:
    raw = str(meta.get("probe_expectation", "")).strip().lower()
    if raw in EXPECT_MODES:
        return raw
    if bool(meta.get("unstable", False)):
        return "reachable"
    return "strict"


def classify_gate_failure(gate: Dict[str, str], expected_gate: str) -> str:
    status = str(gate.get("status", ""))
    rc = str(gate.get("rc", ""))
    reason = str(gate.get("reason_bucket", ""))
    stderr = str(gate.get("stderr", "")).lower()
    if status == expected_gate:
        return "OK"
    if status == "blocked_allowlist":
        return "ALLOWLIST_MISMATCH"
    if rc == "41" and reason == FAIL_POLICY:
        if "local/meta/ssrf target" in stderr:
            return "URL_SAFETY_POLICY_BLOCK"
        return "POLICY_BLOCK_OTHER"
    return "GATE_OTHER_ERROR"


def evaluate_expectation(
    mode: str,
    dns_ok: bool,
    tcp_ok: bool,
    http: Dict[str, str],
    tcp_reason: str,
    gate: Dict[str, str],
) -> Tuple[bool, str, str]:
    response_received = http.get("response_received") == "true"
    tls_ok = http.get("tls_ok") == "true"
    http_reason = http.get("reason_bucket", FAIL_UNKNOWN)

    if mode == "strict":
        if dns_ok and response_received and tls_ok:
            return True, "HTTP", OK
        # Probe realism fallback: gate already completed a successful HTTP fetch.
        if (
            dns_ok
            and gate.get("status") == "allowed_by_gate"
            and gate.get("rc") == "0"
            and gate.get("reason_bucket") == OK
        ):
            return True, "HTTP", OK
        if not dns_ok:
            return False, "NONE", FAIL_DNS
        return False, "NONE", http_reason

    if mode == "reachable":
        if dns_ok and response_received:
            return True, "HTTP", OK
        if dns_ok and tcp_ok:
            return True, "CONNECT", OK
        if dns_ok:
            return False, "DNS_ONLY", http_reason if http_reason != OK else tcp_reason
        return False, "NONE", FAIL_DNS

    # connect_only
    if dns_ok and tcp_ok:
        return True, "CONNECT", OK
    if dns_ok:
        return False, "DNS_ONLY", tcp_reason
    return False, "NONE", FAIL_DNS


def probe_one(
    root: str,
    domain: str,
    probe_host: str,
    tier: int,
    probe_paths: List[str],
    mode: str,
    allowset_all: set[str],
    fetch_allow_tiers: set[int],
) -> Dict[str, str]:
    target_host = probe_host or domain
    dns_ok, dns_addrs, dns_err, dns_reason = dns_probe(target_host)
    tcp_ok, tcp_err, tcp_reason = tcp_probe(target_host)

    if mode == "connect_only":
        http = {
            "response_received": "false",
            "tls_ok": "false",
            "status": "",
            "final_url": f"https://{target_host}/",
            "final_host": "",
            "content_type": "",
            "error": "skipped_connect_only",
            "reason_bucket": OK,
            "probe_path": probe_paths[0] if probe_paths else "/",
        }
    else:
        http = http_probe(target_host, probe_paths)

    gate = gate_probe(root, domain, probe_paths)

    final_host = http.get("final_host", "")
    final_allowlisted = host_in_allowlist(final_host, allowset_all) if final_host else False

    expected_gate = "allowed_by_gate" if tier in fetch_allow_tiers else "blocked_allowlist"
    gate_ok = gate["status"] == expected_gate
    gate_failure_class = classify_gate_failure(gate, expected_gate)

    exp_pass, exp_via, exp_reason = evaluate_expectation(mode, dns_ok, tcp_ok, http, tcp_reason, gate)

    final_status_code = http["status"] if http["status"] else "none"
    if final_status_code == "none" and gate.get("meta_http_status"):
        final_status_code = gate.get("meta_http_status", "none")

    return {
        "domain": domain,
        "tier": str(tier),
        "probe_path": http.get("probe_path", "/"),
        "probe_host": target_host,
        "probe_expectation": mode,
        "probe_pass": "true" if exp_pass else "false",
        "result_type": exp_via if exp_pass else "FAIL",
        "failure_bucket": exp_reason,
        "final_status_code": final_status_code,
        "dns_ok": "true" if dns_ok else "false",
        "dns_addrs": ", ".join(dns_addrs[:4]),
        "dns_error": dns_err,
        "dns_reason_bucket": dns_reason,
        "tcp_ok": "true" if tcp_ok else "false",
        "tcp_error": tcp_err,
        "tcp_reason_bucket": tcp_reason,
        "http_ok": http["response_received"],
        "http_status": http["status"],
        "http_error": http["error"],
        "http_reason_bucket": http["reason_bucket"],
        "final_host": final_host,
        "final_host_allowlisted": "true" if final_allowlisted else "false",
        "gate_status": gate["status"],
        "gate_rc": gate["rc"],
        "gate_expected": expected_gate,
        "gate_ok": "true" if gate_ok else "false",
        "gate_reason_bucket": gate.get("reason_bucket", FAIL_UNKNOWN),
        "gate_failure_class": gate_failure_class,
        "gate_stderr": gate["stderr"],
        "gate_probe_path": gate.get("probe_path", "/"),
    }


def write_csv(path: str, rows: List[Dict[str, str]]) -> None:
    cols = [
        "domain",
        "tier",
        "probe_path",
        "probe_expectation",
        "probe_host",
        "probe_pass",
        "result_type",
        "failure_bucket",
        "final_status_code",
        "dns_ok",
        "dns_addrs",
        "dns_error",
        "dns_reason_bucket",
        "tcp_ok",
        "tcp_error",
        "tcp_reason_bucket",
        "http_ok",
        "http_status",
        "http_error",
        "http_reason_bucket",
        "final_host",
        "final_host_allowlisted",
        "gate_status",
        "gate_rc",
        "gate_expected",
        "gate_ok",
        "gate_reason_bucket",
        "gate_failure_class",
        "gate_probe_path",
        "gate_stderr",
    ]
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(",".join(cols) + "\n")
        for r in rows:
            vals = []
            for c in cols:
                v = (r.get(c) or "").replace('"', '""')
                if any(ch in v for ch in [",", "\n", '"']):
                    v = '"' + v + '"'
                vals.append(v)
            f.write(",".join(vals) + "\n")


def write_markdown(path: str, rows: List[Dict[str, str]], root: str, policy_tiers: List[int]) -> None:
    total = len(rows)
    gate_fail = [r for r in rows if r["gate_ok"] != "true"]
    probe_fail = [r for r in rows if r["probe_pass"] != "true"]
    dns_fail = [r for r in rows if r["dns_ok"] != "true"]
    http_fail = [r for r in rows if r["http_ok"] != "true"]
    redirect_off_allow = [
        r
        for r in rows
        if r["http_ok"] == "true" and r["final_host"] and r["final_host_allowlisted"] != "true"
    ]

    ts = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("# Local Lucy Trust Catalog Site Probe Report\n")
        f.write(f"- Time: {ts}\n")
        f.write(f"- Root: `{root}`\n")
        f.write(f"- Policy fetch_allow_tiers: `{policy_tiers}`\n")
        f.write(f"- Domains tested: {total}\n")
        f.write(f"- Gate expectation failures: {len(gate_fail)}\n")
        f.write(f"- Probe expectation failures: {len(probe_fail)}\n")
        f.write(f"- DNS failures: {len(dns_fail)}\n")
        f.write(f"- HTTPS request failures: {len(http_fail)}\n")
        f.write(f"- Redirected to non-allowlisted host: {len(redirect_off_allow)}\n\n")

        f.write("## Gate Failures (Require Patches)\n")
        if not gate_fail:
            f.write("- None\n")
        else:
            counts: Dict[str, int] = {}
            for r in gate_fail:
                c = r.get("gate_failure_class", "UNKNOWN")
                counts[c] = counts.get(c, 0) + 1
            f.write("- Failure classes:\n")
            for k in sorted(counts.keys()):
                f.write(f"  - `{k}`: {counts[k]}\n")
            for r in gate_fail:
                f.write(
                    f"- `{r['domain']}` tier {r['tier']}: expected `{r['gate_expected']}`, got `{r['gate_status']}` (class=`{r.get('gate_failure_class','UNKNOWN')}`, rc={r['gate_rc']}, reason={r['gate_reason_bucket']})\n"
                )

        f.write("\n## Probe Expectation Failures\n")
        if not probe_fail:
            f.write("- None\n")
        else:
            for r in probe_fail:
                f.write(
                    f"- `{r['domain']}` mode=`{r['probe_expectation']}` result_type=`{r['result_type']}` reason=`{r['failure_bucket']}`\n"
                )

        f.write("\n## Network Failures (External/Environment)\n")
        if not dns_fail and not http_fail:
            f.write("- None\n")
        else:
            for r in rows:
                if r["dns_ok"] != "true":
                    f.write(
                        f"- `{r['domain']}` DNS failed: `{r['dns_error']}` bucket=`{r['dns_reason_bucket']}`\n"
                    )
                elif r["http_ok"] != "true":
                    f.write(
                        f"- `{r['domain']}` HTTP failed: `{r['http_error']}` status=`{r['http_status']}` path=`{r['probe_path']}` bucket=`{r['http_reason_bucket']}`\n"
                    )

        f.write("\n## Redirect Outside Allowlist\n")
        if not redirect_off_allow:
            f.write("- None\n")
        else:
            for r in redirect_off_allow:
                f.write(f"- `{r['domain']}` -> `{r['final_host']}`\n")

        f.write("\n## Domain Results\n")
        f.write("| domain | tier | expectation | probe_host | probe_pass | result_type | failure_bucket | final_status_code | dns | tcp | http | final_host | gate |\n")
        f.write("|---|---:|---|---|---|---|---|---|---|---|---|---|---|\n")
        for r in rows:
            http = "ok" if r["http_ok"] == "true" else f"fail:{r['http_reason_bucket']}"
            dns = "ok" if r["dns_ok"] == "true" else f"fail:{r['dns_reason_bucket']}"
            tcp = "ok" if r["tcp_ok"] == "true" else f"fail:{r['tcp_reason_bucket']}"
            f.write(
                f"| `{r['domain']}` | {r['tier']} | `{r['probe_expectation']}` | `{r['probe_host']}` | `{r['probe_pass']}` | `{r['result_type']}` | `{r['failure_bucket']}` | `{r['final_status_code']}` | {dns} | {tcp} | {http} | `{r['final_host']}` | `{r['gate_status']}` |\n"
            )


def main() -> None:
    root = detect_root()
    catalog = os.path.join(root, "config", "trust", "trust_catalog.yaml")
    policy_path = os.path.join(root, "config", "trust", "policy.yaml")
    gen_all = os.path.join(root, "config", "trust", "generated", "allowlist_all.txt")
    verify = os.path.join(root, "tools", "trust", "verify_trust_lists.sh")

    if not os.path.isfile(catalog):
        fail(f"missing catalog: {catalog}")
    if not os.path.isfile(policy_path):
        fail(f"missing policy: {policy_path}")
    if not os.path.isfile(verify):
        fail(f"missing verify script: {verify}")

    subprocess.run([verify], check=True)

    all_domains = load_generated_domains(gen_all)
    policy = load_policy(policy_path)
    fetch_allow_tiers = set(policy["fetch_allow_tiers"])
    meta = load_catalog_metadata(catalog)
    allow_all_set = set(all_domains)

    canonical_domains = sorted({canonical_catalog_domain(d, meta) for d in all_domains})
    missing = [d for d in canonical_domains if d not in meta]
    if missing:
        fail("domains missing from catalog: " + ", ".join(missing))

    rows: List[Dict[str, str]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        futs = []
        for d in canonical_domains:
            dmeta = meta[d]
            tier = int(dmeta.get("tier", 0))
            probe_host = str(dmeta.get("probe_host", d))
            probe_paths = dmeta.get("probe_paths")
            if not isinstance(probe_paths, list):
                probe_paths = ["/"]
            mode = expectation_mode(dmeta)
            futs.append(
                ex.submit(
                    probe_one,
                    root,
                    d,
                    probe_host,
                    tier,
                    [str(p) for p in probe_paths],
                    mode,
                    allow_all_set,
                    fetch_allow_tiers,
                )
            )
        for fut in concurrent.futures.as_completed(futs):
            rows.append(fut.result())

    rows.sort(key=lambda r: r["domain"])

    out_dir = os.path.join(
        root,
        "tmp",
        "test_reports",
        "trust_probe",
        dt.datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%z"),
    )
    os.makedirs(out_dir, exist_ok=True)
    csv_path = os.path.join(out_dir, "results.csv")
    md_path = os.path.join(out_dir, "report.md")
    json_path = os.path.join(out_dir, "results.json")

    write_csv(csv_path, rows)
    write_markdown(md_path, rows, root, policy["fetch_allow_tiers"])
    with open(json_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(rows, f, indent=2)

    gate_fail = [r for r in rows if r["gate_ok"] != "true"]
    print(f"OUT_DIR={out_dir}")
    print(f"TOTAL={len(rows)}")
    print(f"GATE_FAIL={len(gate_fail)}")
    print(f"CSV={csv_path}")
    print(f"MD={md_path}")
    print(f"JSON={json_path}")
    if gate_fail:
        print("ERR: gate expectation failures detected", file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
