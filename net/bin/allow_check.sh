#!/usr/bin/env bash
set -euo pipefail
host="${1:?host required}"
allowfile="${2:?allowlist file required}"

# normalize
host="${host,,}"
host="${host%.}"
host="${host#www.}"

while IFS= read -r d; do
  [[ -z "$d" ]] && continue
  [[ "$d" =~ ^# ]] && continue
  d="${d,,}"
  d="${d%.}"
  d="${d#www.}"

  # exact domain or subdomain match
  if [[ "$host" == "$d" ]] || [[ "$host" == *".${d}" ]]; then
    exit 0
  fi
done < "$allowfile"

exit 1
