# Local Lucy v10 — Persona Runbook

## Overview

Local Lucy v10 supports a single user-specific persona:

- **Michael** — direct, technically precise, evidence-first, dry pragmatic tone.

A persona becomes active when the user declares their identity (for example, "I am Michael") or when the HMI Control Panel persona selector is set to `Michael`. The active identity is stored in session memory and is used until the user clears it from the HMI or declares a different identity.

> **HMI force switch:** The Control Panel has a `persona` selector that forces the active identity for all models, independent of voice-declared identity. `auto` returns to identity detection from the user's words.

## How Personas Work

Two mechanisms work together at runtime:

1. **Model-level LoRA adapters** — If a persona-tagged Ollama model exists locally (for example, `local-lucy-llama31-michael`), Local Lucy routes LOCAL queries to that model automatically. The adapter was trained on persona-specific datasets and produces the most robust behavior.
2. **Prompt-level persona injection** — If no LoRA tag is installed for the active identity, Local Lucy keeps the base model and injects the matching persona fragment from `config/personas/<name>.txt` after the self-knowledge block in the runtime prompt.

The runtime resolution is handled in `tools/router_py/local_answer.py`.

## Current Adapter Status

| Base model | Ollama tag | Size | Michael | Implementation |
|---|---|---|---|---|
| Llama 3.1 8B Instruct | `local-lucy-llama31` | ~8B | ⚠️ Archived (`local-lucy-llama31-michael`) | Pre-trained adapter backed up to `backups/v10-dev-cleanup/2026-07-04/lora/`; prompt-level fallback is active until restored or retrained |
| Qwen3 14B | `local-lucy` / `local-lucy-fast` / `local-lucy-qwen3` | ~14B | ⚠️ Prompt-level fallback | Cannot train on RTX 3060 12 GB (OOM) |
| Mistral-Nemo 12B | `local-lucy-mistral` | ~12B | ⚠️ Prompt-level fallback | Cannot train on RTX 3060 12 GB (OOM); prompt fallback is used |

> **Legend:** ✅ LoRA adapter installed and registered
> **⚠️** Falls back to prompt-level persona injection
> **🔄** Adapter training or conversion is pending

### Hardware limitation: Qwen3 14B

`Qwen/Qwen3-14B` OOMs during `prepare_model_for_kbit_training` even with rank 4, sequence length 512, batch size 1, and 4-bit quantization on an RTX 3060 12 GB. It is therefore not possible to train LoRA adapters for the Qwen3-based tags in this hardware configuration. They continue to use prompt-level personas, which gives correct tone and behavior for most queries but is less robust than a trained adapter.

### Mistral-Nemo 12B

`mistralai/Mistral-Nemo-Instruct-2407` loads into ~9 GB of VRAM at 4-bit but OOMs during `prepare_model_for_kbit_training` on the RTX 3060 12 GB, leaving no room for the float32 conversion step. Adapters cannot be trained on this hardware, so the Mistral base model uses prompt-level persona injection instead.

## Persona Files

| File | Purpose |
|---|---|
| `config/personas/michael.txt` | Prompt fragment for Michael |
| `backups/v10-dev-cleanup/2026-07-04/lora/datasets/michael.jsonl` | Archived training conversations for Michael LoRA |

## Training a Persona LoRA Adapter

> **Note:** The pre-trained LoRA adapters and datasets were archived to `backups/v10-dev-cleanup/2026-07-04/lora/` as part of the v10-dev cleanup. To use the existing adapter, restore it to `models/lora/` and `data/lora/` or update the corresponding `config/Modelfile.*` ADAPTER paths. The workflow below regenerates the adapter from the built-in spec.

### One adapter manually

```bash
cd ~/lucy-v10
source ui-v10/.venv/bin/activate

# Generate datasets (if not already present)
python3 tools/lora/build_datasets.py

# Train Michael on Llama 3.1 8B
python3 tools/lora/train_persona_lora.py \
    --dataset data/lora/datasets/michael.jsonl \
    --base-tag local-lucy-llama31 \
    --persona michael

# Convert the Safetensors adapter to GGUF for Ollama 0.14.x
HF_TOKEN=... python3 tools/lora/convert_adapters_to_gguf.py \
    --adapter-dir models/lora/local-lucy-llama31/michael

# Register the Ollama tag
ollama create local-lucy-llama31-michael -f config/Modelfile.local-lucy-llama31-michael
```

### Full pipeline

```bash
HF_TOKEN=... tools/lora/train_all_personas.sh
```

This script trains, converts, and registers all adapters that fit in the available VRAM. It runs sequentially because the RTX 3060 12 GB can only train one adapter at a time.

### Rebuild only Ollama tags from existing adapters

```bash
tools/lora/build_persona_models.sh
```

This creates Ollama tags for every adapter directory and Modelfile that already exist under `models/lora/`.

## Evaluating Persona Behavior

Run the golden-case evaluator against a LoRA model:

```bash
python3 tools/lora/evaluate_persona.py --model local-lucy-llama31-michael
```

Run the same cases against the base model with prompt-level persona injection:

```bash
python3 tools/lora/evaluate_persona.py --model local-lucy-llama31 --prompt-persona michael --persona michael

# Test qwen3 14B prompt-level fallback
python3 tools/lora/evaluate_persona.py --model local-lucy --prompt-persona michael --persona michael
```

Golden cases live in `tests/golden_persona_cases.jsonl`.

### Latest validation results (RTX 3060 12 GB)

| Model / path | Persona | Pass rate | Notes |
|---|---|---|---|
| `local-lucy-llama31-michael` (LoRA) | Michael | 100% (9/9) | Trained adapter |
| `local-lucy` + prompt (`local-lucy-qwen3`) | Michael | 88.9% (8/9) | Strong prompt-level compliance |
| `local-lucy-mistral` + prompt | Michael | 88.9% (8/9) | Good direct style after prompt tuning |

> Pass rates are measured against `tests/golden_persona_cases.jsonl` with `--min-pass-rate 60`. Minor variance between runs is normal due to sampling.

## HMI Integration

- The active persona is shown in the HMI Control Panel and in the Runtime Summary status card when an identity is set.
- A "Clear identity" button is available in the Control Panel to return to the default, persona-neutral behavior.
- Persona resolution is transparent to the rest of the pipeline: routing, memory, and provider fallback still work normally.

## Fallback Summary

| Situation | Behavior |
|---|---|
| No identity active | Base model, no persona injection. |
| Identity active + LoRA tag installed | Use persona-tagged LoRA model. |
| Identity active + no LoRA tag installed | Use base model + prompt-level persona fragment. |
| Identity active + LoRA tag missing from Ollama but adapter files exist | Re-run `tools/lora/build_persona_models.sh` to register the tag. |

## References

- `AGENTS.md` — agent-facing pipeline notes
- `tools/router_py/local_answer.py` — runtime persona resolution
- `tools/memory/memory_service.py` — identity storage and retrieval
- `tools/lora/train_persona_lora.py` — QLoRA training script
- `tools/lora/convert_adapters_to_gguf.py` — GGUF conversion for Ollama
- `tools/lora/evaluate_persona.py` — golden-case evaluator
