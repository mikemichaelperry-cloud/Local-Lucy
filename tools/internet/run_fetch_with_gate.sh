#!/usr/bin/env bash
set -euo pipefail

PROMPT=0
if [[ "${1:-}" == "--prompt" ]]; then PROMPT=1; shift; fi

url="${1:-}"
if [[ -z "${url}" ]]; then
  echo "usage: run_fetch_with_gate.sh [--prompt] <url>" >&2
  exit 2
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
LUCY_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
ALLOWLIST_FILE="$LUCY_ROOT/config/trust/generated/allowlist_fetch.txt"
ALLOWLIST_FILTER_FILE="${LUCY_FETCH_ALLOWLIST_FILTER_FILE:-}"
URL_SAFETY_PY="$LUCY_ROOT/tools/internet/url_safety.py"
MAX_FETCH_BYTES="${LUCY_GATE_MAX_BYTES:-1500000}"
CURL_CONNECT_TIMEOUT="${LUCY_GATE_CONNECT_TIMEOUT_S:-8}"
CURL_MAX_TIME="${LUCY_GATE_MAX_TIME_S:-25}"

OK="OK"
FAIL_DNS="FAIL_DNS"
FAIL_CONNECT="FAIL_CONNECT"
FAIL_TLS="FAIL_TLS"
FAIL_TIMEOUT="FAIL_TIMEOUT"
FAIL_HTTP_403="FAIL_HTTP_403"
FAIL_HTTP_401="FAIL_HTTP_401"
FAIL_HTTP_404="FAIL_HTTP_404"
FAIL_HTTP_429="FAIL_HTTP_429"
FAIL_HTTP_5XX="FAIL_HTTP_5XX"
FAIL_HTTP_OTHER="FAIL_HTTP_OTHER"
FAIL_TOO_LARGE="FAIL_TOO_LARGE"
FAIL_REDIRECT_BLOCKED="FAIL_REDIRECT_BLOCKED"
FAIL_NOT_ALLOWLISTED="FAIL_NOT_ALLOWLISTED"
FAIL_POLICY="FAIL_POLICY"
FAIL_UNKNOWN="FAIL_UNKNOWN"

# TODO(phase2): add optional per-domain path allowlisting for high-surface hosts.

require_allowlist_file() {
  if [[ ! -s "$ALLOWLIST_FILE" ]]; then
    echo "ERROR: generated fetch allowlist missing or empty." >&2
    echo "Run:" >&2
    echo "  python3 tools/trust/generate_trust_lists.py" >&2
    echo "  tools/trust/verify_trust_lists.sh" >&2
    return 1
  fi
  if [[ -n "$ALLOWLIST_FILTER_FILE" && ! -s "$ALLOWLIST_FILTER_FILE" ]]; then
    echo "ERROR: router/category allowlist missing or empty: $ALLOWLIST_FILTER_FILE" >&2
    return 1
  fi
  return 0
}

validate_url_policy() {
  local u="$1"
  local out
  if [[ -x "$URL_SAFETY_PY" || -f "$URL_SAFETY_PY" ]]; then
    out="$(python3 "$URL_SAFETY_PY" validate-url "$u" 2>/dev/null || true)"
    if [[ "$out" == OK* ]]; then
      return 0
    fi
    return 1
  fi
  # Fallback only if python validator is unavailable.
  if is_local_or_meta "$u"; then
    return 1
  fi
  case "$u" in
    https://*) return 0 ;;
    *) return 1 ;;
  esac
}

# --- helpers ---
domain_of() {
  if [[ -x "$LUCY_ROOT/net/bin/url_domain.sh" ]]; then
    "$LUCY_ROOT/net/bin/url_domain.sh" "$1" 2>/dev/null || true
  else
    python3 - "$1" <<'PY' 2>/dev/null || true
import sys,urllib.parse
u=urllib.parse.urlparse(sys.argv[1])
h=(u.hostname or "").strip().lower().rstrip('.')
if h.startswith("www."):
  h=h[4:]
print(h)
PY
  fi
}

is_local_or_meta() {
  python3 - "$1" <<'PY'
import sys,ipaddress,urllib.parse,socket
u=urllib.parse.urlparse(sys.argv[1])
h=u.hostname or ""
bad_hosts={"localhost","localhost.localdomain"}
if h in bad_hosts:
  raise SystemExit(0)
try:
  ip=ipaddress.ip_address(h)
  if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved):
    raise SystemExit(0)
except ValueError:
  pass
try:
  infos=socket.getaddrinfo(h, None)
  for info in infos:
    ip=ipaddress.ip_address(info[4][0])
    if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved):
      raise SystemExit(0)
except Exception:
  pass
raise SystemExit(1)
PY
}

allow_domain_in_file() {
  local d="$1"
  local f="$2"
  [[ -n "$d" ]] || return 1
  [[ -s "$f" ]] || return 1

  if [[ -x "$LUCY_ROOT/net/bin/allow_check.sh" ]]; then
    "$LUCY_ROOT/net/bin/allow_check.sh" "$f" "$d" >/dev/null 2>&1 && return 0 || true
    "$LUCY_ROOT/net/bin/allow_check.sh" "$d" "$f" >/dev/null 2>&1 && return 0 || true
    "$LUCY_ROOT/net/bin/allow_check.sh" "$d" >/dev/null 2>&1 && return 0 || true
  fi

  python3 - "$d" "$f" <<'PY2'
import sys
h=sys.argv[1].strip().lower().rstrip('.')
if h.startswith("www."):
  h=h[4:]
f=sys.argv[2]
ok=False
for line in open(f,'r',encoding='utf-8',errors='ignore'):
  s=line.strip().lower().rstrip('.')
  if not s or s.startswith('#'):
    continue
  if s.startswith("www."):
    s=s[4:]
  if h==s or h.endswith('.'+s):
    ok=True
    break
raise SystemExit(0 if ok else 1)
PY2
}

allow_domain() {
  local d="$1"
  [[ -n "$d" ]] || return 1
  allow_domain_in_file "$d" "$ALLOWLIST_FILE" || return 1
  if [[ -n "$ALLOWLIST_FILTER_FILE" ]]; then
    allow_domain_in_file "$d" "$ALLOWLIST_FILTER_FILE" || return 1
  fi
  return 0
}

bucket_http_status() {
  local status="$1"
  case "$status" in
    401) echo "$FAIL_HTTP_401" ;;
    403) echo "$FAIL_HTTP_403" ;;
    404) echo "$FAIL_HTTP_404" ;;
    429) echo "$FAIL_HTTP_429" ;;
    5??) echo "$FAIL_HTTP_5XX" ;;
    ''|000) echo "$FAIL_UNKNOWN" ;;
    *) echo "$FAIL_HTTP_OTHER" ;;
  esac
}

bucket_curl_exit() {
  local rc="$1"
  case "$rc" in
    6) echo "$FAIL_DNS" ;;
    7) echo "$FAIL_CONNECT" ;;
    28) echo "$FAIL_TIMEOUT" ;;
    35|51|53|60) echo "$FAIL_TLS" ;;
    47) echo "$FAIL_HTTP_OTHER" ;;
    *) echo "$FAIL_UNKNOWN" ;;
  esac
}

domain_prefers_uncompressed_fetch() {
  local host="$1"
  [[ -n "$host" ]] || return 1
  case "$host" in
    ec.europa.eu|*.ec.europa.eu) return 0 ;;
  esac
  return 1
}

emit_fetch_meta() {
  local final_url="$1"
  local final_domain="$2"
  local http_status="$3"
  local reason="$4"
  local bytes="$5"
  local total_time_ms="$6"
  local attempts="$7"
  local proto="$8"
  local redirect_count="$9"
  local allowlisted_final="${10}"
  local a1_status="${11}"
  local a1_reason="${12}"
  local a1_proto="${13}"
  local a2_status="${14}"
  local a2_reason="${15}"
  local a2_proto="${16}"

  echo "FETCH_META final_url=${final_url} final_domain=${final_domain} http_status=${http_status} reason=${reason} bytes=${bytes} total_time_ms=${total_time_ms} attempts=${attempts} proto=${proto} redirect_count=${redirect_count} allowlisted_final=${allowlisted_final} attempt1_status=${a1_status} attempt1_reason=${a1_reason} attempt1_proto=${a1_proto} attempt2_status=${a2_status} attempt2_reason=${a2_reason} attempt2_proto=${a2_proto}" >&2
}

run_curl_attempt() {
  local in_url="$1"
  local proto="$2"
  local outfile="$3"

  local errfile outmeta rc status final_url time_s bytes_dl redirects http_version reason final_dom allow_final input_dom
  errfile="$(mktemp /tmp/lucy-fetch-attempt.err.XXXXXX)"
  outmeta="$(mktemp /tmp/lucy-fetch-attempt.meta.XXXXXX)"

  local proto_flags=()
  local content_flags=(--compressed)
  if [[ "$proto" == "http1.1" ]]; then
    proto_flags+=(--http1.1)
  fi
  input_dom="$(domain_of "$in_url")"
  if domain_prefers_uncompressed_fetch "$input_dom"; then
    content_flags=()
  fi

  set +e
  curl -sS -L \
    --connect-timeout "$CURL_CONNECT_TIMEOUT" --max-time "$CURL_MAX_TIME" \
    --retry 1 --retry-delay 1 \
    "${proto_flags[@]}" \
    "${content_flags[@]}" \
    -A "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36" \
    -H "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8" \
    -o "$outfile" \
    -w 'http_status=%{http_code} final_url=%{url_effective} total_time_s=%{time_total} size_download=%{size_download} redirect_count=%{num_redirects} http_version=%{http_version}\n' \
    -- "$in_url" >"$outmeta" 2>"$errfile"
  rc=$?
  set -e

  status="none"
  final_url="$in_url"
  time_s="0"
  bytes_dl="0"
  redirects="0"
  http_version="$proto"

  if [[ -s "$outmeta" ]]; then
    status="$(awk '{for(i=1;i<=NF;i++) if($i ~ /^http_status=/){sub(/^http_status=/,"",$i); print $i}}' "$outmeta")"
    final_url="$(awk '{for(i=1;i<=NF;i++) if($i ~ /^final_url=/){sub(/^final_url=/,"",$i); print $i}}' "$outmeta")"
    time_s="$(awk '{for(i=1;i<=NF;i++) if($i ~ /^total_time_s=/){sub(/^total_time_s=/,"",$i); print $i}}' "$outmeta")"
    bytes_dl="$(awk '{for(i=1;i<=NF;i++) if($i ~ /^size_download=/){sub(/^size_download=/,"",$i); print $i}}' "$outmeta")"
    redirects="$(awk '{for(i=1;i<=NF;i++) if($i ~ /^redirect_count=/){sub(/^redirect_count=/,"",$i); print $i}}' "$outmeta")"
    http_version="$(awk '{for(i=1;i<=NF;i++) if($i ~ /^http_version=/){sub(/^http_version=/,"",$i); print $i}}' "$outmeta")"
  fi

  if [[ -z "$status" ]]; then status="none"; fi
  if [[ -z "$final_url" ]]; then final_url="$in_url"; fi
  if [[ -z "$time_s" ]]; then time_s="0"; fi
  if [[ -z "$bytes_dl" ]]; then bytes_dl="0"; fi
  if [[ -z "$redirects" ]]; then redirects="0"; fi
  if [[ -z "$http_version" ]]; then http_version="$proto"; fi
  if [[ "$http_version" == "2" || "$http_version" == "2.0" ]]; then
    http_version="http2"
  elif [[ "$http_version" == "1.1" ]]; then
    http_version="http1.1"
  elif [[ "$http_version" == "0" ]]; then
    http_version="$proto"
  fi

  if [[ -n "${LUCY_FETCH_FORCE_FINAL_URL:-}" ]]; then
    final_url="$LUCY_FETCH_FORCE_FINAL_URL"
  fi

  final_dom="$(domain_of "$final_url")"
  allow_final="false"
  if [[ -n "$final_dom" ]] && allow_domain "$final_dom"; then
    allow_final="true"
  fi

  reason="$OK"
  if [[ "$rc" -ne 0 ]]; then
    reason="$(bucket_curl_exit "$rc")"
  fi

  if [[ "$reason" == "$OK" ]] && ! validate_url_policy "$final_url"; then
    reason="$FAIL_POLICY"
  fi

  if [[ "$reason" == "$OK" ]] && [[ "$allow_final" != "true" ]]; then
    reason="$FAIL_REDIRECT_BLOCKED"
  fi

  if [[ "$reason" == "$OK" ]]; then
    if [[ "$bytes_dl" =~ ^[0-9]+$ ]] && [[ "$bytes_dl" -gt "$MAX_FETCH_BYTES" ]]; then
      reason="$FAIL_TOO_LARGE"
    elif [[ "$bytes_dl" == "0" || "$status" == "none" || "$status" == "000" ]]; then
      reason="$FAIL_UNKNOWN"
    elif [[ "$status" =~ ^[0-9]+$ ]] && [[ "$status" -ge 400 ]]; then
      reason="$(bucket_http_status "$status")"
    fi
  fi

  rm -f "$outmeta" "$errfile"
  echo "${rc}|${reason}|${status}|${final_url}|${final_dom}|${bytes_dl}|${time_s}|${redirects}|${http_version}|${allow_final}"
}

if ! require_allowlist_file; then
  emit_fetch_meta "$url" "$(domain_of "$url")" "none" "$FAIL_POLICY" "0" "0" "0" "none" "0" "false" "none" "$FAIL_POLICY" "none" "none" "none" "none"
  exit 2
fi

if [[ "${LUCY_DEBUG_ROUTE:-0}" == "1" ]]; then
  echo "DEBUG_ROUTE allowlist file loaded = ${ALLOWLIST_FILE}" >&2
  if [[ -n "${ALLOWLIST_FILTER_FILE}" ]]; then
    echo "DEBUG_ROUTE allowlist filter loaded = ${ALLOWLIST_FILTER_FILE}" >&2
  fi
fi

if ! validate_url_policy "$url"; then
  echo "blocked: local/meta/ssrf target" >&2
  emit_fetch_meta "$url" "$(domain_of "$url")" "none" "$FAIL_POLICY" "0" "0" "0" "none" "0" "false" "none" "$FAIL_POLICY" "none" "none" "none" "none"
  exit 41
fi

dom="$(domain_of "$url")"
if ! allow_domain "$dom"; then
  echo "blocked: domain not allowlisted ($dom)" >&2
  emit_fetch_meta "$url" "$dom" "none" "$FAIL_NOT_ALLOWLISTED" "0" "0" "0" "none" "0" "false" "none" "$FAIL_NOT_ALLOWLISTED" "none" "none" "none" "none"
  exit 40
fi

if [[ "$PROMPT" == "1" ]] && [[ -t 0 ]]; then
  echo -n "Proceed? Type yes to continue: " >&2
  read -r ans || ans=""
  [[ "$ans" == "yes" ]] || exit 1
fi

tmp1="$(mktemp /tmp/lucy-gate-fetch1.XXXXXX)"
tmp2="$(mktemp /tmp/lucy-gate-fetch2.XXXXXX)"

IFS='|' read -r a1_rc a1_reason a1_status a1_final_url a1_final_dom a1_bytes a1_time_s a1_redirects a1_httpver a1_allow <<< "$(run_curl_attempt "$url" "http2" "$tmp1")"

final_reason="$a1_reason"
final_status="$a1_status"
final_url="$a1_final_url"
final_dom="$a1_final_dom"
final_bytes="$a1_bytes"
final_time_s="$a1_time_s"
final_redirects="$a1_redirects"
final_proto="$a1_httpver"
attempts="1"
a2_status="none"
a2_reason="none"
a2_httpver="none"

if [[ "$a1_reason" != "$OK" ]]; then
  IFS='|' read -r _a2_rc a2_reason a2_status a2_final_url a2_final_dom a2_bytes a2_time_s a2_redirects a2_httpver a2_allow <<< "$(run_curl_attempt "$url" "http1.1" "$tmp2")"
  attempts="2"
  final_reason="$a2_reason"
  final_status="$a2_status"
  final_url="$a2_final_url"
  final_dom="$a2_final_dom"
  final_bytes="$a2_bytes"
  final_time_s="$a2_time_s"
  final_redirects="$a2_redirects"
  final_proto="http2_fallback_http1.1"
fi

# Convert seconds string like 0.123456 into milliseconds integer.
final_time_ms="$(python3 - "$final_time_s" <<'PY'
import sys
try:
    v=float(sys.argv[1])
except Exception:
    v=0.0
print(int(round(v*1000.0)))
PY
)"

allowlisted_final="false"
if [[ -n "$final_dom" ]] && allow_domain "$final_dom"; then
  allowlisted_final="true"
fi

emit_fetch_meta "$final_url" "$final_dom" "$final_status" "$final_reason" "$final_bytes" "$final_time_ms" "$attempts" "$final_proto" "$final_redirects" "$allowlisted_final" "$a1_status" "$a1_reason" "http2" "$a2_status" "$a2_reason" "http1.1"

if [[ "$final_reason" != "$OK" ]]; then
  case "$final_reason" in
    "$FAIL_NOT_ALLOWLISTED"|"$FAIL_REDIRECT_BLOCKED")
      exit 40
      ;;
    "$FAIL_POLICY")
      exit 41
      ;;
    *)
      exit 42
      ;;
  esac
fi

if [[ "$attempts" == "2" ]]; then
  head -c "$MAX_FETCH_BYTES" "$tmp2"
else
  head -c "$MAX_FETCH_BYTES" "$tmp1"
fi

rm -f "$tmp1" "$tmp2"
