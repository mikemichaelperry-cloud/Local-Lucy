#!/usr/bin/env bash
set -euo pipefail

J=$(~/lucy/tools/internet/tool_router.sh fetch_url_v1 \
  '{"url":"https://en.wikipedia.org/api/rest_v1/page/summary/Ada_Lovelace","max_bytes":120000}')

TXT=$(
  printf '%s\n' "$J" \
  | jq -r '.data.content | fromjson | .extract' \
  | sed '1s/^/PARAGRAPH:\n/; $a\\nEND\n'
)

OUT=$(printf '%s\n' "$TXT" | ollama run local-lucy-mem \
  'Summarize the paragraph between PARAGRAPH and END in 1 sentence. Use only that text.')

echo "$OUT"

# Fail if it claims missing input / JSON-only / etc.
if echo "$OUT" | grep -qiE "did not receive|does not contain|only.*json|no text beyond"; then
  echo "FAIL: model indicated missing input text" >&2
  exit 1
fi
