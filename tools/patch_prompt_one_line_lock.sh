#!/usr/bin/env bash
set -euo pipefail

PROMPT="${1:-$HOME/lucy/config/system_prompt.dev.txt}"
BK="$PROMPT.bak.$(date +%F_%H%M%S)"

[[ -f "$PROMPT" ]] || { echo "ERROR: missing $PROMPT" >&2; exit 1; }

cp -a "$PROMPT" "$BK"
echo "Backup: $BK"

python3 - "$PROMPT" <<'PY'
import sys, re, pathlib
p = pathlib.Path(sys.argv[1])
txt = p.read_text(encoding="utf-8", errors="replace")

# Add/replace an "EVIDENCE-ONLY" block at end (idempotent)
block = """
# === EVIDENCE-ONLY MODE (LOCAL LUCY DEV) ===
# When the user asks: "without guessing or assuming" or requests evidence-only:
# - State ONLY what is directly supported by text provided in this chat/session.
# - If a fact is not present, say: "Not provided in this session."
# - Do NOT invent tool permissions, file access, internet access, or memory access.
# - If unsure, ask for the missing input or refuse.
"""

# remove any previous copy of this block (roughly)
txt = re.sub(r"\n# === EVIDENCE-ONLY MODE \(LOCAL LUCY DEV\) ===.*?\n(?=\Z)", "\n", txt, flags=re.S)

txt = txt.rstrip() + "\n" + block.strip() + "\n"
p.write_text(txt, encoding="utf-8")
print("Patched prompt:", p)
PY

echo "=== diff (tail) ==="
tail -n 60 "$PROMPT"
