#!/usr/bin/env bash
set -euo pipefail

PROMPT="$HOME/lucy/config/system_prompt.dev.txt"
[[ -s "$PROMPT" ]] || { echo "ERROR: missing/empty: $PROMPT" >&2; exit 1; }

BK="$PROMPT.bak.$(date +%F_%H%M%S)"
cp -a "$PROMPT" "$BK"

python3 - <<'PY'
import pathlib, re, sys

p = pathlib.Path.home() / "lucy/config/system_prompt.dev.txt"
txt = p.read_text(encoding="utf-8")

marker = "### OPTION_A_EVIDENCE_ONLY_END"

guard = (
"\n"
"Transform-guard (STRICT):\n"
"- For summaries/rewrites/extractions of user-provided text: you MUST NOT add any facts not explicitly present in that text.\n"
"- Do NOT add numbers, speeds, examples, countries, train names, or general knowledge unless they appear in the provided text.\n"
"- If the user input is a single sentence, your summary must stay within that sentence's information content.\n"
"- If the user asks for examples and none are in the provided text, refuse with the unified refusal line.\n"
"\n"
)

if marker not in txt:
    print(f"ERROR: marker not found: {marker}", file=sys.stderr)
    sys.exit(2)

if "Transform-guard (STRICT):" in txt:
    print("Transform-guard already present. No change.")
    sys.exit(0)

# Insert guard immediately before marker (once)
txt2, n = re.subn(re.escape(marker), guard + marker, txt, count=1)
if n != 1:
    print("ERROR: failed to insert guard (unexpected match count)", file=sys.stderr)
    sys.exit(3)

p.write_text(txt2, encoding="utf-8")
print("Inserted Transform-guard before OPTION_A end marker.")
PY

echo "Backup: $BK"
echo "OK"
