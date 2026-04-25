#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  enforce_news_plurality.sh DOMAINS_FILE MIN_COUNT
USAGE
}

main() {
  if [ $# -ne 2 ]; then
    usage
    exit 2
  fi

  f="$1"
  min="$2"

  if [ ! -f "$f" ]; then
    echo "ERROR: missing domains file: $f" >&2
    exit 2
  fi

  n="$(grep -c '^[^[:space:]]' "$f" || true)"
  if [ "$n" -lt "$min" ]; then
    echo "INSUFFICIENT_EVIDENCE: need $min distinct trusted domains, have $n" >&2
    exit 3
  fi

  echo "OK: plurality=$n"
}

main "$@"
