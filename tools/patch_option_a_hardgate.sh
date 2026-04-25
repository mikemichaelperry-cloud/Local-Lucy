#!/usr/bin/env bash
set -euo pipefail
PROMPT="$HOME/lucy/config/system_prompt.dev.txt"
[[ -s "$PROMPT" ]] || { echo "ERROR: missing/empty: $PROMPT" >&2; exit 1; }

BK="$PROMPT.bak.$(date +%F_%H%M%S)"
cp -a "$PROMPT" "$BK"

python3 - <<'PY'
import pathlib, sys

p = pathlib.Path.home() / "lucy/config/system_prompt.dev.txt"
txt = p.read_text(encoding="utf-8")

block = (
"=== OPTION A: EVIDENCE-ONLY HARDGATE (NON-NEGOTIABLE) ===\n"
"Refusal line (exact, one line, no extra text): Not provided in this session's user messages.\n"
"\n"
"1) Fact questions (prices, speeds, news, 'how fast', 'what is', 'give examples'):\n"
"   - If the answer is not explicitly present in the user's message, you MUST output the refusal line and stop.\n"
"\n"
"2) Transform requests (summarize / rewrite / extract / paraphrase):\n"
"   - You MUST use ONLY the information explicitly present in the provided text.\n"
"   - You MUST NOT add numbers, examples, named entities, or general knowledge.\n"
"   - If the provided text contains no numbers/examples, you MUST NOT introduce any.\n"
"\n"
"Stop rule:\n"
"   - When you output the refusal line, output NOTHING ELSE.\n"
"=== END OPTION A HARDGATE ===\n"
"\n"
)

if "=== OPTION A: EVIDENCE-ONLY HARDGATE" in txt:
    print("Hardgate already present. No change.")
    sys.exit(0)

# Put it right at the very top
p.write_text(block + txt, encoding="utf-8")
print("Inserted Option A hardgate at top of prompt.")
PY

echo "Backup: $BK"
echo "OK"
