#!/usr/bin/env bash
set -euo pipefail

SP="$HOME/lucy/config/system_prompt.dev.txt"
MF="$HOME/lucy/config/Modelfile.local-lucy-mem"
MODEL="local-lucy-mem"
TS="$(date +%F_%H%M%S)"

cp -a "$SP" "$SP.bak.$TS"
echo "Backup: $SP.bak.$TS"

# Append a final override block at the very end (last instruction wins).
cat >> "$SP" <<'RULES'

# FINAL OVERRIDE: internet/tool access wording (strict)
- If the user asks whether you have internet access, tools, browsing, web search, or anything similar:
  reply with EXACTLY:
  "No. I have no internet or tool access in this session."
  If helpful, add ONE more sentence:
  "Paste the text or source and I will analyze it."
- Do NOT mention: operating envelope, constraints, policy, permissions, rules, keel, modes, or memory in this answer.
RULES

ollama create "$MODEL" -f "$MF"
echo "Done."
