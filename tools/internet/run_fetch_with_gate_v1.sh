#!/usr/bin/env bash
set -euo pipefail

URL="${1:-}"
[[ -n "$URL" ]] || { echo '{"error":"missing_url"}'; exit 2; }

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
LUCY_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"

# --- Extract domain
domain="$("$LUCY_ROOT/net/bin/url_domain.sh" "$URL" 2>/dev/null || true)"
[[ -n "$domain" ]] || { echo '{"error":"bad_url"}'; exit 2; }

# --- Block localhost / link-local / private ranges using existing gate if present
# (Your current v0 wrapper already has the correct logic; we reuse the same helpers)
# Quick allowlist check (internal matcher is now robust)
allow_domain() {
  local d="$1"
  local generated_allowfile="$LUCY_ROOT/config/trust/generated/allowlist_fetch.txt"
  local allowfile="$generated_allowfile"
  if [[ ! -f "$allowfile" ]]; then
    return 1
  fi
  [[ -f "$allowfile" ]] || return 1
  python3 - "$d" "$allowfile" <<'PY'
import sys
d=sys.argv[1].strip().lower()
f=sys.argv[2]
ok=False
for line in open(f,'r',encoding='utf-8',errors='ignore'):
  line=line.strip().lower()
  if not line or line.startswith('#'): continue
  if d==line or d.endswith("."+line):
    ok=True; break
raise SystemExit(0 if ok else 1)
PY
}

# Deny local hostnames outright
case "$domain" in
  localhost|localhost.*) echo "{\"blocked\":\"local_domain\",\"domain\":\"$domain\"}"; exit 41 ;;
esac

# Deny literal IPs in local ranges (cheap SSRF guard)
if [[ "$domain" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then
  # block loopback + link-local + RFC1918 + meta IP
  case "$domain" in
    127.*|0.*|10.*|192.168.*|169.254.*) echo "{\"blocked\":\"local_ip\",\"ip\":\"$domain\"}"; exit 41 ;;
  esac
  # 172.16.0.0/12
  IFS=. read -r a b c d <<<"$domain"
  if [[ "$a" == "172" && "$b" =~ ^(1[6-9]|2[0-9]|3[0-1])$ ]]; then
    echo "{\"blocked\":\"rfc1918_172\",\"ip\":\"$domain\"}"; exit 41
  fi
fi

# Block cloud metadata explicitly (defense-in-depth)
if [[ "$URL" == http://169.254.169.254/* || "$URL" == https://169.254.169.254/* ]]; then
  echo '{"blocked":"metadata_ip"}'; exit 41
fi

# Allowlist enforcement
if ! allow_domain "$domain"; then
  echo "{\"blocked\":\"domain_not_allowlisted\",\"domain\":\"$domain\"}"
  exit 40
fi

# --- Call the working fetch gate (stdout=body, stderr includes FETCH_META)
tmp_body="$(mktemp /tmp/lucy-fetchv1.body.XXXXXX)"
tmp_err="$(mktemp /tmp/lucy-fetchv1.err.XXXXXX)"
set +e
timeout 12s "$LUCY_ROOT/tools/internet/run_fetch_with_gate.sh" "$URL" >"$tmp_body" 2>"$tmp_err"
rc=$?
set -e

if [[ "$rc" -ne 0 ]]; then
  # Preserve block/failure exit semantics for callers/tests.
  cat "$tmp_err" >&2 || true
  rm -f "$tmp_body" "$tmp_err"
  exit "$rc"
fi

# Envelope: v1 JSON wrapper around fetched content.
python3 - "$tmp_body" "$tmp_err" "$URL" <<'PY2'
import hashlib, json, re, sys, time

body_path, err_path, req_url = sys.argv[1], sys.argv[2], sys.argv[3]
raw = open(body_path, "rb").read()
err = open(err_path, "r", encoding="utf-8", errors="replace").read()
sha = hashlib.sha256(raw).hexdigest()

meta_line = ""
for line in err.splitlines():
    if line.startswith("FETCH_META "):
        meta_line = line

kv = {}
for k, v in re.findall(r'([A-Za-z0-9_]+)=([^\s]+)', meta_line):
    kv[k] = v

content = raw.decode("utf-8", "replace")
out = {
    "ok": True,
    "trust_level": "external_unverified",
    "data": {
        "url": req_url,
        "final_url": kv.get("final_url", req_url),
        "final_domain": kv.get("final_domain", ""),
        "http_status": kv.get("http_status", ""),
        "content": content,
    },
    "meta": {
        "fetched_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "tool_version": 1,
        "backend": "run_fetch_with_gate+envelope",
        "output_sha256": sha,
        "bytes": len(raw),
    },
}
print(json.dumps(out, ensure_ascii=False))
PY2
rm -f "$tmp_body" "$tmp_err"
