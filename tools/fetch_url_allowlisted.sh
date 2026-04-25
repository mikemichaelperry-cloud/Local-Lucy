#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DEFAULT="$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)"
ROOT="${LUCY_ROOT:-$ROOT_DEFAULT}"
RSS_EXTRACT="${LUCY_RSS_EXTRACT_TOOL:-$ROOT/tools/rss_extract.py}"
ALLOW_DOMAINS_PRIMARY="$ROOT/config/trust/generated/allowlist_all_tier12.txt"
ALLOW_DOMAINS_FALLBACK="$ROOT/config/trust/generated/allowlist_fetch.txt"
ALLOW_DOMAINS=""
ALLOW_DOMAINS_FILTER="${LUCY_FETCH_ALLOWLIST_FILTER_FILE:-}"
GATE_FETCH="$ROOT/tools/internet/run_fetch_with_gate.sh"

# Hard caps (prevent huge downloads / terminal floods).
MAX_BYTES="${LUCY_FETCH_MAX_BYTES:-1048576}"
MAX_OUT_BYTES="${LUCY_FETCH_MAX_OUT_BYTES:-200000}"

usage() {
  cat <<'USAGE'
Usage:
  fetch_url_allowlisted.sh URL
Notes:
  Deterministic allowlist fetcher.
  - Refuses non-https URLs.
  - Refuses domains not in allowlist.
  - Outputs extracted text to stdout (best-effort).
USAGE
}

require_allowlist() {
  if [ -n "$ALLOW_DOMAINS_FILTER" ]; then
    if [ ! -s "$ALLOW_DOMAINS_FILTER" ]; then
      echo "ERROR: router/category allowlist missing or empty: $ALLOW_DOMAINS_FILTER" >&2
      exit 2
    fi
    if [ "${LUCY_TRUST_DEBUG:-0}" = "1" ]; then
      echo "DEBUG_TRUST allow_domains_filter_file=${ALLOW_DOMAINS_FILTER}" >&2
    fi
  fi
  if [ -s "$ALLOW_DOMAINS_PRIMARY" ]; then
    ALLOW_DOMAINS="$ALLOW_DOMAINS_PRIMARY"
    if [ "${LUCY_TRUST_DEBUG:-0}" = "1" ]; then
      echo "DEBUG_TRUST allow_domains_file=${ALLOW_DOMAINS}" >&2
    fi
    return 0
  fi
  if [ -s "$ALLOW_DOMAINS_FALLBACK" ]; then
    ALLOW_DOMAINS="$ALLOW_DOMAINS_FALLBACK"
    if [ "${LUCY_TRUST_DEBUG:-0}" = "1" ]; then
      echo "DEBUG_TRUST allow_domains_file=${ALLOW_DOMAINS}" >&2
    fi
    return 0
  fi
  if [ -z "$ALLOW_DOMAINS" ] || [ ! -s "$ALLOW_DOMAINS" ]; then
    echo "ERROR: generated fetch allowlist missing or empty." >&2
    echo "Run:" >&2
    echo "  python3 tools/trust/generate_trust_lists.py" >&2
    echo "  tools/trust/verify_trust_lists.sh" >&2
    exit 2
  fi
}

require_gate() {
  if [ ! -x "$GATE_FETCH" ]; then
    echo "ERROR: missing fetch gate: $GATE_FETCH" >&2
    exit 2
  fi
}

fetch_html() {
  local url="$1"
  local tmp_html tmp_err rc
  tmp_html="$(mktemp /tmp/lucy-fetch-html.XXXXXX)"
  tmp_err="$(mktemp /tmp/lucy-fetch-err.XXXXXX)"

  set +e
  "$GATE_FETCH" "$url" >"$tmp_html" 2>"$tmp_err"
  rc=$?
  set -e

  if [ "$rc" -ne 0 ]; then
    cat "$tmp_err" >&2 || true
    rm -f "$tmp_html" "$tmp_err"
    return 1
  fi

  grep -E '^FETCH_META ' "$tmp_err" >&2 || true
  head -c "$MAX_BYTES" "$tmp_html"
  rm -f "$tmp_html" "$tmp_err"
}

main() {
  if [ $# -ne 1 ]; then
    usage
    exit 2
  fi

  require_allowlist
  require_gate

  url="$1"

  case "$url" in
    https://*) ;;
    *)
      echo "ERROR: only https URLs allowed" >&2
      exit 2
      ;;
  esac

  html="$(fetch_html "$url" || true)"
  if [ -z "$html" ]; then
    echo "ERROR: fetch failed or empty response" >&2
    exit 2
  fi

  # RSS/Atom deterministic extractor
  if printf "%s" "$html" | grep -Eqi '(<rss|<feed)'; then
    if [ ! -x "$RSS_EXTRACT" ]; then
      echo "ERROR: missing RSS extractor: $RSS_EXTRACT" >&2
      exit 2
    fi
    printf "%s" "$html" | "$RSS_EXTRACT"
    exit 0
  fi

  if command -v lynx >/dev/null 2>&1; then
    set +o pipefail
    printf "%s" "$html" | lynx -dump -stdin -nolist | head -c "$MAX_OUT_BYTES"
    set -o pipefail
    exit 0
  fi

  # Fallback: deterministic crude HTML stripping.
  set +o pipefail
  printf "%s" "$html" \
    | sed -e 's/<script[^>]*>[^<]*<\/script>/ /gI' \
          -e 's/<style[^>]*>[^<]*<\/style>/ /gI' \
          -e 's/<[^>]*>/ /g' \
          -e 's/&nbsp;/ /g' \
          -e 's/&amp;/\&/g' \
          -e 's/&quot;/"/g' \
          -e "s/&apos;/'/g" \
          -e 's/&lt;/</g' \
          -e 's/&gt;/>/g' \
    | tr -s '[:space:]' ' ' \
    | sed -e 's/^[[:space:]]\+//' -e 's/[[:space:]]\+$//'
}

main "$@"
