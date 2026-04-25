#!/usr/bin/env bash
# ROLE: LEGACY / DEPRECATED SURFACE
# Retained for compatibility/history; do not use for new workflows.
# Preferred replacement: tools/start_local_lucy_opt_experimental_v6_dev.sh
set -euo pipefail

BASE_MODEL="${1:-llama3.1:8b}"
RUNTIME_MODEL="local-lucy-mem"
TS="$(date -Is)"

SYSTEM_PROMPT_FILE="$HOME/lucy/config/system_prompt.dev.txt"
MEM_FILE="$HOME/lucy/memory/memory.txt"
AUDIT_LOG="$HOME/lucy/audit/audit.log"
MODELFILE="$HOME/lucy/config/Modelfile.${RUNTIME_MODEL}"
KEEL_FILE="$HOME/lucy/keel/keel.yaml"

echo "=== Local Lucy + Memory v0 ==="
echo "Base model:  $BASE_MODEL"
echo "Runtime:     $RUNTIME_MODEL"
echo "System:      $SYSTEM_PROMPT_FILE"
echo "Memory:      $MEM_FILE"
echo "Modelfile:   $MODELFILE"
echo "Session start: $TS"
echo

# Explicit enable: memory is OFF unless LUCY_MEM=on
MEM_STATUS="off"
if [[ "${LUCY_MEM:-off}" == "on" ]]; then
  if [[ -s "$MEM_FILE" ]]; then
    MEM_STATUS="on"
  else
    echo "WARNING: LUCY_MEM=on but memory file is empty" >&2
  fi
fi

mkdir -p "$(dirname "$AUDIT_LOG")"
echo "$TS | START | runtime=$RUNTIME_MODEL base=$BASE_MODEL memory=$MEM_STATUS" >> "$AUDIT_LOG"

# Build SYSTEM text
SYS_TEXT="$(cat "$SYSTEM_PROMPT_FILE")"

# Keel banner (read-only) if present
if [[ -s "$KEEL_FILE" ]]; then
  SYS_TEXT+=$'\n\n'"$("$HOME/lucy/tools/keel_banner.sh")"$'\n'
else
  SYS_TEXT+=$'\n\nKeel: missing\n'
fi


# Always declare memory status explicitly (removes ambiguity)
SYS_TEXT+=$'\n\n'"Persistent memory status: ${MEM_STATUS}"$'\n'

# If memory is OFF, enforce hard response for any memory questions
if [[ "$MEM_STATUS" != "on" ]]; then
  SYS_TEXT+="- No persistent memory block is present in this session."$'\n'
  SYS_TEXT+="- For ANY question about memory, stored items, past chats, or prior sessions, reply with exactly: not in memory"$'\n'
fi

# If memory is ON, inject it as a read-only block
if [[ "$MEM_STATUS" == "on" ]]; then
  SYS_TEXT+=$'\n\n'"Persistent memory (read-only, user-approved):"$'\n'
  SYS_TEXT+="- You may use the memory text below as context in this session."$'\n'
  SYS_TEXT+="- You MUST NOT claim you wrote, edited, stored, or updated persistent memory."$'\n'
  SYS_TEXT+="- If something is not present in the memory block, reply with exactly: not in memory"$'\n\n'
  SYS_TEXT+="--- BEGIN PERSISTENT MEMORY ---"$'\n'
  SYS_TEXT+="$(cat "$MEM_FILE")"$'\n'
  SYS_TEXT+="--- END PERSISTENT MEMORY ---"$'\n'
fi

# Write Modelfile
mkdir -p "$(dirname "$MODELFILE")"
cat > "$MODELFILE" <<EOM
FROM ${BASE_MODEL}

SYSTEM """
${SYS_TEXT}
"""
EOM

# Create/update runtime wrapper model, then run
ollama create "${RUNTIME_MODEL}" -f "$MODELFILE" >/dev/null
ollama run "${RUNTIME_MODEL}"

TS_END="$(date -Is)"
echo "$TS_END | END   | runtime=$RUNTIME_MODEL base=$BASE_MODEL memory=$MEM_STATUS" >> "$AUDIT_LOG"
