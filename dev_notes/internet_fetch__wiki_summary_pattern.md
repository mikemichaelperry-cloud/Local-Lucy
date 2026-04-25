# Wikipedia summary fetch pattern (preferred)

Use REST summary endpoint (stable JSON) and extract only .extract text.
Add explicit delimiters so the model cannot invent context.

Example:
  J=$(~/lucy/tools/internet/tool_router.sh fetch_url_v1 \
        '{"url":"https://en.wikipedia.org/api/rest_v1/page/summary/Ada_Lovelace","max_bytes":120000}')

  printf '%s\n' "$J" \
    | jq -r '.data.content | fromjson | .extract' \
    | sed '1s/^/PARAGRAPH:\n/; $a\\nEND\n' \
    | ollama run local-lucy-mem \
      'Summarize the paragraph between PARAGRAPH and END in 1 sentence. Use only that text.'
