#!/usr/bin/env bash
set -euo pipefail

URL="${1:?Usage: lucy_fetch.sh <url> [max_kb]}"
MAX_KB="${2:-400}"  # cap to keep paste manageable
BASE="$HOME/lucy/net"
ALLOW="$BASE/allowlist.txt"
AUDIT="$HOME/lucy/audit/net.audit.log"

host="$("$BASE/bin/url_domain.sh" "$URL")"
if ! "$BASE/bin/allow_check.sh" "$host" "$ALLOW"; then
  echo "BLOCKED (not in allowlist): $host" >&2
  echo "Edit allowlist: $ALLOW" >&2
  exit 2
fi

TS="$(date -Is)"
TMP="$(mktemp)"
RAW="$(mktemp)"

# Fetch (tight timeouts, follow redirects, identify as LucyFetch)
curl -fsSL --max-time 20 -A "LucyFetch/0.1" "$URL" > "$RAW"

# Cap size (bytes)
MAX_BYTES=$((MAX_KB * 1024))
BYTES="$(wc -c < "$RAW" | tr -d ' ')"
if (( BYTES > MAX_BYTES )); then
  head -c "$MAX_BYTES" "$RAW" > "$TMP"
  NOTE="TRUNCATED to ${MAX_KB}KB"
else
  cp -a "$RAW" "$TMP"
  NOTE="OK"
fi

SHA="$(sha256sum "$TMP" | awk '{print $1}')"
BYTES2="$(wc -c < "$TMP" | tr -d ' ')"

# Try to render to text if w3m exists; otherwise leave as-is (v0)
OUT="$(mktemp)"
if command -v w3m >/dev/null 2>&1; then
  # w3m can render HTML to readable text
  w3m -dump -cols 120 "$URL" > "$OUT" || cp -a "$TMP" "$OUT"
else
  cp -a "$TMP" "$OUT"
fi

# Print paste-ready block
echo "----- BEGIN INTERNET V0 SOURCE -----"
echo "timestamp: $TS"
echo "url: $URL"
echo "host: $host"
echo "sha256: $SHA"
echo "bytes: $BYTES2"
echo "note: $NOTE"
echo "----- BEGIN CONTENT -----"
cat "$OUT"
echo
echo "----- END CONTENT -----"
echo "----- END INTERNET V0 SOURCE -----"

# Audit
printf '%s | %s | host=%s | sha256=%s | bytes=%s | %s\n' "$TS" "$URL" "$host" "$SHA" "$BYTES2" "$NOTE" >> "$AUDIT"

rm -f "$RAW" "$TMP" "$OUT"
