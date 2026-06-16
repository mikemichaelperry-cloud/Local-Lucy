# ADR 0002: Default Local Model Switched to llama3.1:8b

## Status
Accepted — implemented 2026-06-07

## Context
The previous default local model was `qwen3:14b`. It has baked-in privacy guardrails that override system prompts, causing it to refuse personal/family queries even when explicit persistent facts were present in the prompt. This behavior is unfixable without fine-tuning.

## Decision
Switch the default local model to `llama3.1:8b` (`local-lucy-llama31`) with:
- `num_ctx 4096` (doubled from 2048)
- `temperature 0.0`
- `repeat_penalty 1.2`
- A strengthened system prompt explicitly permitting questions about the user, family, and pets.

Keep qwen3:14b and mistral-nemo as selectable alternatives.

## Consequences
- Faster cold/warm starts (7.5s / 5.2s vs 25.6s / 23.4s).
- Zero personal-query refusals in benchmarks.
- Lower VRAM usage (~8.5 GB), allowing Whisper to share the GPU.
- Larger context window (4096 tokens).
