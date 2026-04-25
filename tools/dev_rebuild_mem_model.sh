#!/usr/bin/env bash
set -euo pipefail

MODEL="local-lucy-mem"
MODELFILE="${MODELFILE:-$HOME/lucy/config/Modelfile.local-lucy-mem}"

echo "=== Rebuild dev model ==="
echo "Model:     $MODEL"
echo "Modelfile: $MODELFILE"

if [[ ! -f "$MODELFILE" ]]; then
  echo "ERROR: Modelfile not found: $MODELFILE" >&2
  exit 1
fi

# Rebuild (idempotent)
ollama create "$MODEL" -f "$MODELFILE"

echo "=== Rebuild complete ==="
