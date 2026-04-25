import argparse
import hashlib
import json
import os
import time
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError

try:
    import yaml
except Exception:
    yaml = None

from url_safety import parse_and_validate_url
from extract_text import html_to_text

def load_yaml(path: str) -> dict:
    if yaml is None:
        raise RuntimeError("PyYAML not installed. Install python3-yaml or convert configs to JSON.")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def load_allowlist_txt(path: str) -> dict:
    exact = []
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            s = raw.strip().lower()
            if not s or s.startswith("#"):
                continue
            exact.append(s)
    return {
        "_format": "allowlist_txt",
        "https_only": True,
        "exact": sorted(set(exact)),
        "subdomains": [],
        "ports": [443],
    }

def load_trusted_config(path: str) -> dict:
    if path.lower().endswith(".txt"):
        return load_allowlist_txt(path)
    data = load_yaml(path)
    if isinstance(data, dict):
        data.setdefault("_format", "trusted_yaml")
    return data

def domain_allowed(host: str, trusted: dict) -> bool:
    exact = set((trusted.get("exact") or []))
    subs = set((trusted.get("subdomains") or []))
    if host in exact or host in subs:
        return True
    if trusted.get("_format") == "allowlist_txt":
        return any(host.endswith("." + d) for d in exact)
    return False

class LimitedRedirect(HTTPRedirectHandler):
    def __init__(self, max_redirects: int, trusted: dict):
        super().__init__()
        self.max_redirects = max_redirects
        self.trusted = trusted
        self.count = 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.count += 1
        if self.count > self.max_redirects:
            raise HTTPError(req.full_url, code, "too many redirects", headers, fp)

        url, host, port, err = parse_and_validate_url(newurl)
        if err:
            raise HTTPError(req.full_url, code, f"redirect url rejected: {err}", headers, fp)
        if not domain_allowed(host, self.trusted):
            raise HTTPError(req.full_url, code, "redirect domain not allowlisted", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)

def normalize_content_type(ct: str) -> str:
    if not ct:
        return ""
    return ct.split(";")[0].strip().lower()

def ensure_dirs(path: str) -> None:
    os.makedirs(path, exist_ok=True)

def _sniff_fail(reason: str) -> tuple[bool, str]:
    return (False, reason)

def sniff_content(content_type: str, raw: bytes) -> tuple[bool, str]:
    head = raw[:4096]
    # Reject NUL bytes for anything we treat as text.
    if content_type in ("text/html", "text/plain", "application/json", "application/xml"):
        if b"\x00" in head:
            return _sniff_fail("nul byte in text content")

    if content_type == "application/pdf":
        if not head.startswith(b"%PDF-"):
            return _sniff_fail("pdf magic missing")
        return (True, "ok")

    # For text-ish, do minimal heuristics.
    h_l = head.lstrip()

    if content_type == "application/json":
        if not (h_l.startswith(b"{") or h_l.startswith(b"[")):
            return _sniff_fail("json prefix mismatch")
        return (True, "ok")

    if content_type == "application/xml":
        if not h_l.startswith(b"<"):
            return _sniff_fail("xml prefix mismatch")
        return (True, "ok")

    if content_type == "text/html":
        # Look for html markers early; not perfect but blocks obvious binaries.
        low = head.lower()
        if (b"<html" not in low) and (b"<!doctype" not in low) and (b"<head" not in low):
            return _sniff_fail("html markers missing")
        return (True, "ok")

    if content_type == "text/plain":
        # If it's "plain", we accept broadly as long as it is not binary-ish.
        return (True, "ok")

    return _sniff_fail("unknown content type in sniff")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", required=True)
    ap.add_argument("--url-map", required=True)
    ap.add_argument("--trusted", help="Legacy YAML trust config or generated allowlist .txt")
    ap.add_argument("--allowlist", help="Generated allowlist .txt (preferred)")
    ap.add_argument("--policy", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    url_map = load_yaml(args.url_map)
    trusted_path = args.allowlist or args.trusted
    if not trusted_path:
        print("ERR: one of --allowlist or --trusted is required")
        raise SystemExit(2)
    trusted = load_trusted_config(trusted_path)
    policy = load_yaml(args.policy)

    entry = (url_map.get("urls") or {}).get(args.key)
    if not entry or "url" not in entry:
        print("ERR: unknown url key")
        raise SystemExit(3)

    url = entry["url"]
    url, host, port, err = parse_and_validate_url(url)
    if err:
        print(f"ERR: url rejected: {err}")
        raise SystemExit(4)
    declared = (entry.get("domain") or "").strip().lower()
    if not declared:
        print("ERR: url_map entry missing domain")
        raise SystemExit(15)
    if host != declared:
        print("ERR: url host does not match declared domain")
        raise SystemExit(16)
        print(f"ERR: url rejected: {err}")
        raise SystemExit(4)
    if not domain_allowed(host, trusted):
        print("ERR: domain not allowlisted")
        raise SystemExit(5)

    allowed_ports = set(trusted.get("ports") or [443])
    if port not in allowed_ports:
        print("ERR: port not allowed")
        raise SystemExit(6)

    max_redirects = int(((policy.get("redirects") or {}).get("max")) or 3)
    max_bytes = int(((policy.get("limits") or {}).get("max_bytes")) or 3000000)

    connect_t = int(((policy.get("timeouts") or {}).get("connect_seconds")) or 5)
    total_t = int(((policy.get("timeouts") or {}).get("total_seconds")) or 25)

    allow_ct = set((policy.get("content_types") or {}).get("allow") or [])
    allow_ct = set([c.lower() for c in allow_ct])

    out_root = args.out
    cache_by_url = os.path.join(out_root, "cache", "by_url")
    cache_by_sha = os.path.join(out_root, "cache", "by_sha256")
    logs_dir = os.path.join(out_root, "logs")
    ensure_dirs(cache_by_url)
    ensure_dirs(cache_by_sha)
    ensure_dirs(logs_dir)

    ts = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    safe_key = args.key.replace("/", "_")
    url_dir = os.path.join(cache_by_url, safe_key)
    ensure_dirs(url_dir)

    meta_path = os.path.join(url_dir, "meta.json")
    if os.path.exists(meta_path):
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        print(json.dumps({"status": "cached", "key": args.key, "sha256": meta.get("sha256"), "timestamp": meta.get("timestamp")}))
        return

    opener = build_opener(LimitedRedirect(max_redirects, trusted))

    # Avoid accepting compression bombs silently by preferring identity.
    req = Request(url, method="GET", headers={
        "User-Agent": "local-lucy-evidence-fetch/1.0",
        "Accept": ", ".join(sorted(allow_ct)),
        "Accept-Encoding": "identity",
    })

    start = time.time()
    raw = b""
    final_url = url
    final_host = host
    status_code = 0
    content_type = ""

    try:
        with opener.open(req, timeout=connect_t) as resp:
            status_code = getattr(resp, "status", 200)
            final_url = resp.geturl()
            purl, phost, pport, perr = parse_and_validate_url(final_url)
            if perr:
                print(f"ERR: final url rejected: {perr}")
                raise SystemExit(7)
            if phost != declared:
                print("ERR: final host does not match declared domain")
                raise SystemExit(17)
                print(f"ERR: final url rejected: {perr}")
                raise SystemExit(7)
            if not domain_allowed(phost, trusted):
                print("ERR: final domain not allowlisted")
                raise SystemExit(8)

            final_host = phost
            content_type = normalize_content_type(resp.headers.get("Content-Type", ""))

            if content_type not in allow_ct:
                print("ERR: content-type not allowed")
                raise SystemExit(9)

            while True:
                if (time.time() - start) > total_t:
                    print("ERR: total timeout")
                    raise SystemExit(10)
                chunk = resp.read(65536)
                if not chunk:
                    break
                raw += chunk
                if len(raw) > max_bytes:
                    print("ERR: max size exceeded")
                    raise SystemExit(11)

    except HTTPError as e:
        print(f"ERR: http error: {e.code}")
        raise SystemExit(12)
    except URLError:
        print("ERR: url error")
        raise SystemExit(13)

    ok, why = sniff_content(content_type, raw)
    if not ok:
        print(f"ERR: content sniff failed: {why}")
        raise SystemExit(14)

    sha = hashlib.sha256(raw).hexdigest()

    raw_path = os.path.join(url_dir, "raw.bin")
    with open(raw_path, "wb") as f:
        f.write(raw)

    extracted = ""
    if content_type == "text/html":
        extracted = html_to_text(raw.decode("utf-8", errors="replace"))
    elif content_type in ("text/plain", "application/json", "application/xml"):
        extracted = raw.decode("utf-8", errors="replace")
    elif content_type == "application/pdf":
        extracted = ""

    txt_path = os.path.join(url_dir, "extracted.txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(extracted)

    meta = {
        "key": args.key,
        "url": url,
        "final_url": final_url,
        "domain": final_host,
        "content_type": content_type,
        "bytes": len(raw),
        "sha256": sha,
        "timestamp": ts,
        "status_code": status_code,
        "single_source_ok": bool(entry.get("tags") and "standards" in entry.get("tags")),
        "sniff": "ok",
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, sort_keys=True)

    sha_dir = os.path.join(cache_by_sha, sha)
    ensure_dirs(sha_dir)
    try:
        os.link(raw_path, os.path.join(sha_dir, "raw.bin"))
    except OSError:
        pass

    log_line = json.dumps({"t": ts, "key": args.key, "domain": final_host, "sha256": sha, "bytes": len(raw), "ct": content_type, "sniff": "ok"})
    with open(os.path.join(logs_dir, "fetch.log"), "a", encoding="utf-8") as f:
        f.write(log_line + "\n")

    print(json.dumps({"status": "fetched", "key": args.key, "domain": final_host, "sha256": sha, "timestamp": ts}))

if __name__ == "__main__":
    main()
