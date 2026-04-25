#!/usr/bin/env python3
import ipaddress
import re
import socket
import sys
from urllib.parse import urlparse

METADATA_HOSTS = {"169.254.169.254"}
LOCALHOST_NAMES = {"localhost"}
IP_LITERAL_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")

def is_ip_literal(host: str) -> bool:
    return bool(IP_LITERAL_RE.match(host or ""))

def _ip_is_forbidden(ip: ipaddress._BaseAddress) -> bool:
    if ip.is_private:
        return True
    if ip.is_loopback:
        return True
    if ip.is_link_local:
        return True
    if ip.is_multicast:
        return True
    if ip.is_unspecified:
        return True
    if getattr(ip, "is_reserved", False):
        return True
    return False

def resolve_and_validate_host(host: str) -> str | None:
    h = host.strip().lower()
    try:
        infos = socket.getaddrinfo(h, None, proto=socket.IPPROTO_TCP)
    except Exception:
        return "dns resolution failed"

    # Collect unique IP strings
    ips = []
    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        ip_str = sockaddr[0]
        if ip_str and ip_str not in ips:
            ips.append(ip_str)

    if not ips:
        return "no resolved addresses"

    for ip_str in ips:
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            return "invalid resolved ip"
        if _ip_is_forbidden(ip):
            return "resolved to forbidden network"

    return None

def forbid_host(host: str) -> str | None:
    if not host:
        return "empty host"
    h = host.strip().lower()

    if h in LOCALHOST_NAMES:
        return "localhost forbidden"
    if h in METADATA_HOSTS:
        return "metadata endpoint forbidden"

    if is_ip_literal(h):
        # IP literals forbidden outright per policy.
        return "ip literal forbidden"

    # DNS-to-private defense: hostnames must not resolve to forbidden ranges.
    reason = resolve_and_validate_host(h)
    # DNS failures are not proof of SSRF/local routing. Allow the fetch layer to
    # classify transport errors (DNS timeout/outage vs policy violation).
    if reason and reason not in {"dns resolution failed", "no resolved addresses"}:
        return reason

    return None

def parse_and_validate_url(url: str) -> tuple[str, str, int, str | None]:
    p = urlparse(url)
    if p.scheme != "https":
        return "", "", 0, "https only"
    host = (p.hostname or "").lower()
    port = p.port or 443

    reason = forbid_host(host)
    if reason:
        return "", "", 0, reason

    if p.username or p.password:
        return "", "", 0, "userinfo forbidden"
    if p.fragment:
        return "", "", 0, "fragment forbidden"

    return p.geturl(), host, port, None

def _cli_validate_url(url: str) -> int:
    norm_url, host, port, reason = parse_and_validate_url(url)
    if reason:
        print(f"ERR reason={reason}")
        return 1
    print(f"OK url={norm_url} host={host} port={port}")
    return 0

def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] != "validate-url":
        print("usage: url_safety.py validate-url <url>", file=sys.stderr)
        return 2
    return _cli_validate_url(argv[2])

if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
