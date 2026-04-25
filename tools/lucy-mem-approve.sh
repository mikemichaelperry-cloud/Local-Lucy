#!/usr/bin/env bash
set -euo pipefail

BASE="/home/mike/lucy"
INBOX="$BASE/memory/inbox"
APP="$BASE/memory/approved"
MEM="$BASE/memory/memory.txt"
IDX="$BASE/memory/index.jsonl"
TS="$(date -Is)"

ID="${1:-}"
if [[ -z "$ID" ]]; then
  echo "usage: lucy-mem-approve.sh <proposal-id>"
  echo "tip: ls -1 $INBOX"
  exit 2
fi

SRC="$INBOX/$ID.txt"
if [[ ! -f "$SRC" ]]; then
  echo "not found: $SRC"
  exit 3
fi

DST="$APP/$ID.txt"
mv "$SRC" "$DST"

{
  echo
  echo "----"
  echo "[MEMORY ITEM] id=$ID approved_at=$TS"
  cat "$DST"
} >> "$MEM"

python3 - <<PY >> "$IDX"
import json
print(json.dumps({"ts":"$TS","event":"approve","id":"$ID","file":"$DST"}))
PY

echo "OK: approved -> $DST"
echo "OK: appended to -> $MEM"
