#!/usr/bin/env bash
set -euo pipefail

MODEL="local-lucy-mem"
Q="${*:-}"

REFUSAL="Not provided in this session's user messages."

# OPTION A: EVIDENCE-ONLY (allowlist)
# Allowed:
#   Summarize:/Rewrite:/Extract: <user-provided text>
# Everything else: refuse (one line).
if ! echo "$Q" | grep -Eqi '^(summarize|rewrite|extract)\s*:'; then
  echo "$REFUSAL"
  exit 0
fi

# Transform query: operate ONLY on text after the first colon.
SRC="${Q#*:}"
SRC="${SRC#"${SRC%%[![:space:]]*}"}"   # ltrim
SRC="${SRC%"${SRC##*[![:space:]]}"}"   # rtrim

# If user provided no text to transform, refuse.
if [[ -z "$SRC" ]]; then
  echo "$REFUSAL"
  exit 0
fi

# STRICT transform-guard:
# For short inputs, avoid model calls (prevents added facts).
# Special case: extract -> one item per sentence (deterministic).
if [[ ${#SRC} -le 160 ]]; then
  if echo "$Q" | grep -Eqi "^extract[[:space:]]*:"; then
    printf "%s" "$SRC" | awk '
      {
        gsub(/[[:space:]]+/, " ");
      }
      {
        while (match($0, /[^.!?]+[.!?]*/)) {
          s = substr($0, RSTART, RLENGTH);
          gsub(/^ +| +$/, "", s);
          if (s != "") print s;
          $0 = substr($0, RSTART + RLENGTH);
        }
      }
    '
    exit 0
  fi
  echo "$SRC"
  exit 0
fi

# For longer pasted text, let the model summarize/rewrite/extract,
# but force refusal to exactly one line if it triggers.
out="$(ollama run "$MODEL" "$Q")" || true
if echo "$out" | grep -Fxq "$REFUSAL"; then
  echo "$REFUSAL"
else
  echo "$out"
fi
