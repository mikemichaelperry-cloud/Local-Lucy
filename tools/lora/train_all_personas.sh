#!/usr/bin/env bash
# Train, convert, and register all persona LoRA adapters for Local Lucy.
# This script runs sequentially because the RTX 3060 12 GB can only train
# one adapter at a time. It resumes training for adapters already present.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

source ui-v10/.venv/bin/activate

LLAMA_CPP_ROOT="${LLAMA_CPP_ROOT:-/tmp/llama.cpp}"
EPOCHS="${EPOCHS:-8}"
BATCH_SIZE="${BATCH_SIZE:-1}"
GRAD_ACCUM="${GRAD_ACCUM:-4}"

# (base_tag persona dataset seed)
# NOTE: qwen3 14B and mistral-nemo 12B OOM during prepare_model_for_kbit_training
# on the RTX 3060 12 GB even at conservative QLoRA settings. They fall back to
# prompt-level personas at runtime. Only Llama 3.1 8B adapters are trained here.
JOBS=(
    "local-lucy-llama31 michael data/lora/datasets/michael.jsonl 42"
)

for job in "${JOBS[@]}"; do
    read -r base_tag persona dataset seed <<< "$job"
    adapter_dir="models/lora/$base_tag/$persona"
    tag="$base_tag-$persona"

    if [[ -f "$adapter_dir/adapter_model.safetensors" ]]; then
        echo "[skip train] Adapter exists: $adapter_dir"
    else
        echo "[train] $base_tag / $persona"
        python3 tools/lora/train_persona_lora.py \
            --dataset "$dataset" \
            --base-tag "$base_tag" \
            --persona "$persona" \
            --epochs "$EPOCHS" \
            --batch-size "$BATCH_SIZE" \
            --grad-accum "$GRAD_ACCUM" \
            --seed "$seed" || train_rc=$?

        if [[ "${train_rc:-0}" -ne 0 ]]; then
            echo "[warn] Training failed for $tag (exit $train_rc). Skipping conversion/registration."
            # Don't let a failed training stop the rest of the queue.
            unset train_rc
            continue
        fi
        unset train_rc
    fi

    if [[ -f "$adapter_dir/adapter.gguf" ]]; then
        echo "[skip convert] GGUF exists: $adapter_dir/adapter.gguf"
    else
        echo "[convert] $adapter_dir"
        HF_TOKEN="${HF_TOKEN:-}" python3 tools/lora/convert_adapters_to_gguf.py \
            --adapter-dir "$adapter_dir" \
            --llama-cpp-root "$LLAMA_CPP_ROOT"
    fi

    if ollama list | grep -q "^$tag:latest"; then
        echo "[skip create] Ollama tag exists: $tag"
    else
        echo "[create] ollama create $tag"
        ollama create "$tag" -f "config/Modelfile.$tag"
    fi
done

echo "All persona adapters trained, converted, and registered."
