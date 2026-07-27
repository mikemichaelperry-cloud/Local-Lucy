#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)"

J=$("${ROOT}/tools/internet/tool_router.sh" fetch_url_v1 \
  '{"url":"https://en.wikipedia.org/api/rest_v1/page/summary/Ada_Lovelace","max_bytes":120000}')

TXT=$(
  printf '%s\n' "$J" \
  | jq -r '.data.content | fromjson | .extract' \
  | sed '1s/^/PARAGRAPH:\n/; $a\\nEND\n'
)

OUT=$(printf '%s\n' "$TXT" | ollama run local-lucy-llama31 \
  'Summarize the paragraph between PARAGRAPH and END in 1 sentence. Use only that text.')

echo "$OUT"

# Fail if it claims missing input / JSON-only / etc.
if echo "$OUT" | grep -qiE "did not receive|does not contain|only.*json|no text beyond"; then
  echo "FAIL: model indicated missing input text" >&2
  exit 1
fi
