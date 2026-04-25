#!/usr/bin/env bash
set -euo pipefail

SP="$HOME/lucy/config/system_prompt.dev.txt"
MF="$HOME/lucy/config/Modelfile.local-lucy-mem"
MODEL="local-lucy-mem"
TS="$(date +%F_%H%M%S)"

backup() { cp -a "$1" "$1.bak.$TS"; echo "Backup: $1.bak.$TS"; }

echo "=== Backing up ==="
backup "$SP"
backup "$MF"

echo
echo "=== Patching system prompt (tone for tool requests) ==="

# Insert a strict block after the first line (keeps it simple and deterministic).
awk '
NR==1 {print; print ""; print "STRICT TOOL/TONE RULES (override):"; print "- If the user asks you to search/browse/use tools, and tools are NOT enabled in this session, respond with ONE sentence: \"No. I have no internet or tool access in this session.\""; print "- Do NOT say: \"I am not allowed\" / \"I cannot\" / \"policy\" / \"permissions\"."; print "- Do NOT mention memory when answering tool requests."; print "- If helpful, add ONE more short sentence: \"Paste the text or source and I will analyze it.\""; print ""; next}
{print}
' "$SP" > "$SP.tmp"
mv "$SP.tmp" "$SP"

echo
echo "=== Rebuild model ==="
ollama create "$MODEL" -f "$MF"

echo "=== Done ==="
