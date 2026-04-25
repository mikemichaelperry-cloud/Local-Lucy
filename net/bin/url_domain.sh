#!/usr/bin/env bash
set -euo pipefail
url="${1:?url required}"
# Crude extractor for gate logging/allowlist checks; normalize only syntax variants.
host="$(printf '%s' "$url" | sed -E 's#^[a-zA-Z]+://##; s#/.*$##')"
host="${host##*@}"   # strip userinfo if present
host="${host%%:*}"   # strip port if present
host="${host,,}"     # lowercase
host="${host%.}"     # strip trailing root dot
host="${host#www.}"  # normalize common www variant
printf '%s\n' "$host"
