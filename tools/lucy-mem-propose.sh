#!/usr/bin/env bash
set -euo pipefail

BASE="/home/mike/lucy"
INBOX="$BASE/memory/inbox"
IDX="$BASE/memory/index.jsonl"
TS="$(date -Is)"
ID="$(date +%Y%m%d-%H%M%S)-$RANDOM"

TEXT="${1:-}"
if [[ -z "$TEXT" ]]; then
  echo "usage: lucy-mem-propose.sh \"text to propose\""
  exit 2
fi

FILE="$INBOX/$ID.txt"
{
  echo "[PROPOSAL]"
  echo "id: $ID"
  echo "created_at: $TS"
  echo
  echo "$TEXT"
  echo
} > "$FILE"

# Optional index log (jsonl)
python3 - <<PY >> "$IDX"
import json
print(json.dumps({"ts":"$TS","event":"propose","id":"$ID","file":"$FILE"}))
PY

echo "OK: proposed memory -> $FILE"
