#!/usr/bin/env bash
set -euo pipefail

URL="${1:?Usage: lucy_clip.sh <url> <keyword1> [keyword2 ...]}"
shift
KEYWORDS=("$@")

# Fetch as text (uses your allowlist + auditing)
TEXT="$(~/lucy/net/bin/lucy_fetch.sh "$URL" 300)"

# Extract content only (between markers), then grep windows
CONTENT="$(printf '%s\n' "$TEXT" | sed -n '/^----- BEGIN CONTENT -----$/,/^----- END CONTENT -----$/p')"

echo "----- BEGIN INTERNET V0 CLIP -----"
echo "url: $URL"
echo "keywords: ${KEYWORDS[*]}"
echo "----- BEGIN CLIPPED CONTENT -----"

# For each keyword, show ~12 lines before/after matches, de-dup, cap total lines
for k in "${KEYWORDS[@]}"; do
  printf '%s\n' "$CONTENT" | grep -in -C 12 -- "$k" || true
done | awk 'NF' | head -n 220

echo "----- END CLIPPED CONTENT -----"
echo "----- END INTERNET V0 CLIP -----"
