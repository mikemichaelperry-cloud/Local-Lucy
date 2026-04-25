#!/usr/bin/env bash
set -euo pipefail

MODEL="local-lucy-mem"
MF="$HOME/lucy/config/Modelfile.local-lucy-mem"
BK="$HOME/lucy/config/Modelfile.local-lucy-mem.bak.$(date +%F_%H%M%S)"

echo "=== Fix: remove tool-instructions from Modelfile ==="
echo "Modelfile: $MF"
[[ -f "$MF" ]] || { echo "ERROR: missing $MF" >&2; exit 1; }

cp -a "$MF" "$BK"
echo "Backup:   $BK"

# Drop from any line containing "TOOLS ENABLED" (even if indented) to EOF.
awk '
  BEGIN{drop=0}
  $0 ~ /TOOLS ENABLED/ {drop=1}
  drop==0 {print}
' "$MF" > "$MF.tmp"
mv "$MF.tmp" "$MF"
echo "Removed:  TOOLS ENABLED block (if present)"

# Append a HARD no-tools rule INSIDE a SYSTEM block (valid Modelfile syntax)
cat >> "$MF" <<'EOT'

SYSTEM """
Tool access is DISABLED.
- Never output JSON with "tool_call".
- Never mention "search_web", "fetch_url", or waiting for TOOL_RESULT.
- If asked for current events, say you have no internet and cannot verify.
"""
EOT

echo "=== Rebuild model: $MODEL ==="
ollama create "$MODEL" -f "$MF"

echo "=== Verify Modelfile has no tool directives ==="
grep -nE 'TOOLS ENABLED|Available tools:|search_web|tool_call|TOOL_RESULT' "$MF" || echo "OK: no tool directives found"

echo "=== Done ==="
