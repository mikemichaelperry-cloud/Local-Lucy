#!/usr/bin/env bash
set -euo pipefail

MF="$HOME/lucy/config/Modelfile.local-lucy-mem"
SP="$HOME/lucy/config/system_prompt.dev.txt"
MODEL="local-lucy-mem"
TS="$(date +%F_%H%M%S)"

backup() {
  local f="$1"
  [[ -f "$f" ]] || { echo "ERROR: missing $f" >&2; exit 1; }
  cp -a "$f" "$f.bak.$TS"
  echo "Backup: $f.bak.$TS"
}

strip_from_tools_enabled_to_eof() {
  local f="$1"
  # Drop everything from the first line that starts with TOOLS ENABLED to EOF
  # (Works for both Modelfile and system_prompt.dev.txt)
  awk 'BEGIN{drop=0} /^TOOLS ENABLED/{drop=1} drop==0{print}' "$f" > "$f.tmp"
  mv "$f.tmp" "$f"
}

ensure_modelfile_system_quotes_closed() {
  local f="$1"
  # If SYSTEM triple-quotes exist but only appear once, append closing triple-quotes.
  local count
  count="$(grep -c '"""' "$f" || true)"
  if [[ "$count" -eq 1 ]]; then
    printf '\n"""\n' >> "$f"
    echo 'Fixed: appended closing """ to Modelfile'
  fi
}

echo "=== Backing up ==="
backup "$MF"
backup "$SP"

echo
echo "=== Stripping TOOLS blocks ==="
strip_from_tools_enabled_to_eof "$MF"
strip_from_tools_enabled_to_eof "$SP"

echo
echo "=== Repairing Modelfile quoting (if needed) ==="
ensure_modelfile_system_quotes_closed "$MF"

echo
echo "=== Verify no tool instructions remain ==="
grep -nE 'TOOLS ENABLED|tool_call|search_web|fetch_url|TOOL_RESULT|To use a tool|emit a tool_call' \
  "$MF" "$SP" || echo "OK: no tool-instructions found."

echo
echo "=== Rebuild ollama model: $MODEL ==="
ollama create "$MODEL" -f "$MF"

echo "=== Done ==="
