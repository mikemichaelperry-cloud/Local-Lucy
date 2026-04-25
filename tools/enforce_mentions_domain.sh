#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  enforce_mentions_domain.sh DOMAINS_FILE
Reads candidate output from stdin.
Passes through if:
  - output contains the exact refusal sentence, OR
  - output mentions at least one domain in DOMAINS_FILE
Else:
  - emits wrapped deterministic refusal and exits 3
USAGE
}

main() {
  if [ $# -ne 1 ]; then
    usage
    exit 2
  fi

  f="$1"
  if [ ! -f "$f" ]; then
    echo "ERROR: missing domains file: $f" >&2
    exit 2
  fi

  buf="$(cat)"

  # If the model (or upstream) is refusing, allow it through without domain attribution.
  if printf "%s" "$buf" | grep -Fq "Insufficient evidence from trusted sources."; then
    printf "%s\n" "$buf"
    exit 0
  fi

  hit=0
  while IFS= read -r dom; do
    [ -z "$dom" ] && continue
    if printf "%s" "$buf" | grep -Fqi "$dom"; then
      hit=1
      break
    fi
  done < "$f"

  if [ "$hit" -ne 1 ]; then
    echo "VALIDATION_FAILED: no domain attribution" >&2
    printf "%s\n" "BEGIN_VALIDATED"
    printf "%s\n" "Insufficient evidence from trusted sources."
    printf "%s\n" "END_VALIDATED"
    exit 3
  fi

  printf "%s\n" "$buf"
}

main "$@"
