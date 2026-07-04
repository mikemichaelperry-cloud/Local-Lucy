#!/usr/bin/env bash
# Build Ollama tags for Local Lucy persona adapters.
# Only creates tags whose adapter directories exist under models/lora/.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
CONFIG_DIR="$ROOT/config"
LORA_DIR="$ROOT/models/lora"

BASE_TAGS=(
    local-lucy-llama31
    local-lucy
    local-lucy-fast
    local-lucy-mistral
)

PERSONAS=(michael)

for base_tag in "${BASE_TAGS[@]}"; do
    for persona in "${PERSONAS[@]}"; do
        adapter_dir="$LORA_DIR/$base_tag/$persona"
        modelfile="$CONFIG_DIR/Modelfile.$base_tag-$persona"
        tag="$base_tag-$persona"

        if [[ ! -d "$adapter_dir" ]]; then
            echo "[skip] Adapter not found: $adapter_dir"
            continue
        fi

        if [[ ! -f "$modelfile" ]]; then
            echo "[skip] Modelfile not found: $modelfile"
            continue
        fi

        echo "[build] ollama create $tag -f $modelfile"
        ollama create "$tag" -f "$modelfile"
    done
done

echo "Persona model build complete."
