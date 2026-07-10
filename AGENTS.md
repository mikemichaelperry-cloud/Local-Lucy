# Local Lucy v10 — Agent Instructions

> **READ `SESSION_CONTEXT.md` FIRST at every session start.**
> It contains the current branch, git state, environment variables, and latest changes.
> This file contains the rules; `SESSION_CONTEXT.md` contains the live state.

---

## Authority

- **Working root:** `/home/mike/lucy-v10`
- **Active branch:** `v10-dev`
- **Frozen:** V9 is tagged `local-lucy-v9-frozen-2026-05-28`. Never modify it.
- **Default model:** `local-lucy-llama31` (llama3.1:8b via Ollama)

---

## Session Lifecycle

### At Session Start (Mandatory)
1. Read `SESSION_CONTEXT.md` to understand current state
2. Run `git status --short` and `git log --oneline -5` to verify it matches
3. Read `AGENTS.md` (this file) for rules

### At Session End / Handoff (Mandatory)
1. Update `SESSION_CONTEXT.md` with:
   - Any new commits
   - Working tree changes
   - New TODOs completed or discovered
   - Any architectural decisions
2. `git add SESSION_CONTEXT.md && git commit -m "docs: update SESSION_CONTEXT.md"`
3. If changes were made, ensure working tree is clean before ending

---

## Operating Principles

- No optimistic behavior
- No silent side effects
- No hallucinated files
- Test every change
- Prefer Python over shell for logic
- Prefer `Edit` over `Write` for incremental changes
- Make MINIMAL changes

---

## Boundaries (Do Not Cross Without Approval)

| Area | Rule |
|------|------|
| Router classification | Do not change ModernBERT or keyword guard behavior |
| SQLite schema | Do not modify `lucy_state.db` or `memory.db` schema |
| HMI redesign | Forbidden per user constraint |
| Model weights | Do not retrain or replace embedding index without explicit instruction |
| Voice runtime | Do not modify whisper.cpp or kokoro integration |
| Persona LoRA adapters | Training/conversion may be run when explicitly requested; safe to create tags and rerun build scripts |

**Allowed changes:**
- `execution_engine.py`, `execution_engine_state.py` — state persistence
- `classify.py` — routing guards (with tests)
- `payload_builders.py` — pure formatting
- Tests in `tools/router_py/test_*.py` and `ui-v10/tests/test_*.py`
- Documentation, config, scripts, CI

---

## Key Files

| File | Role | Touch with care |
|------|------|-----------------|
| `tools/router_py/main.py` | Entry point | Yes — keep request_id contract |
| `tools/router_py/request_pipeline.py` | Pipeline choke point | Yes — frozen dataclass contract |
| `tools/router_py/execution_engine.py` | Dispatcher | Yes — all routes must write state |
| `tools/router_py/execution_engine_state.py` | StateWriter (JSON + SQLite) | Yes — public API must not break |
| `tools/router_py/classify.py` | Intent classification + guards | Yes — add tests for new guards |
| `tools/router_py/payload_builders.py` | Shared pure payload builders | Yes — both routers depend on this |
| `tools/router_py/request_types.py` | Centralized frozen dataclasses | Yes — schema changes ripple |
| `ui-v10/app/services/state_store.py` | HMI reads JSON state | No — read-only per constraints |
| `ui-v10/app/panels/status_panel.py` | HMI displays state | No — read-only per constraints |
| `ui-v10/app/backend/*.py` | **RE-EXPORT WRAPPERS ONLY** | Never add logic here |

**Critical:** `ui-v10/app/backend/*.py` are 3–9 line wrappers. Edit `tools/router_py/` and let wrappers pick it up. This has been a repeated footgun.

---

## Environment Variables

```bash
LUCY_ROOT=~/lucy-v10                    # Project root
LUCY_RUNTIME_NAMESPACE_ROOT=~/.local/share/local-lucy   # XDG data (or legacy ~/.codex-api-home)
LUCY_RUNTIME_AUTHORITY_ROOT=~/lucy-v10  # Code authority validation
LUCY_UI_ROOT=~/lucy-v10/ui-v10          # HMI path
LUCY_OLLAMA_API_URL=http://127.0.0.1:11434/api/generate
LUCY_LOCAL_MODEL=local-lucy-llama31
LUCY_AUTO_LEARN=0                       # Set 0 during development to prevent mutation

# Deprecated: Python router/execution are the default in V10.
# LUCY_ROUTER_PY=1
# LUCY_EXEC_PY=1
```

---

## Test Commands

```bash
# Full router suite (CPU only, ~1min40s)
cd ~/lucy-v10
source ui-v10/.venv/bin/activate
python -m pytest tools/router_py/ -q

# Medical routing specifically
python -m pytest tools/router_py/test_medical_evidence_routing.py -v

# HMI offscreen tests
QT_QPA_PLATFORM=offscreen python3 ui-v10/tests/test_comprehensive_hmi_inspection.py

# Live end-to-end (single request)
python3 -c "import sys; sys.path.insert(0,'tools'); from router_py.main import execute_plan_python; \
  r = execute_plan_python('What is 2+2?', timeout=30); print(r.status, r.route)"
```

---

## Persona LoRA Pipeline

The primary runtime supports a single user-specific persona (Michael). It is triggered by identity declarations such as "I am Michael" or by the HMI Control Panel persona selector. Two mechanisms work together:

1. **Prompt-level persona injection** — `tools/router_py/local_answer.py` injects the matching fragment from `config/personas/<name>.txt` whenever an identity is active. The fragment is injected **after** the self-knowledge block so it is the last high-level instruction before the user turn.
2. **Model-level LoRA adapters** — If a persona-tagged Ollama model exists (e.g., `local-lucy-llama31-michael`), Local Lucy resolves to that model automatically; otherwise it falls back to the base model + prompt fragment.

### Hardware limits on RTX 3060 12 GB

| Base model | Persona path | Notes |
|------------|--------------|-------|
| `local-lucy-llama31` (llama3.1:8b) | LoRA adapter | Archived to `backups/v10-dev-cleanup/2026-07-04/lora/`; retrain or restore to use |
| `local-lucy-mistral` (mistral-nemo:12b) | **Prompt-level fallback** | LoRA training OOMs at `prepare_model_for_kbit_training` on 12 GB VRAM; prompt fallback is seamless |
| `local-lucy` / `local-lucy-fast` / `local-lucy-qwen3` (qwen3:14b) | **Prompt-level fallback** | LoRA training OOMs at `prepare_model_for_kbit_training` on 12 GB VRAM; fallback is seamless via `local_answer.py` |

### Files
- `tools/lora/build_datasets.py` — generates `data/lora/datasets/michael.jsonl`
- `tools/lora/train_persona_lora.py` — QLoRA training per base model/persona
- `tools/lora/convert_adapters_to_gguf.py` — converts Safetensors adapters to GGUF for Ollama 0.14.x
- `tools/lora/build_modelfiles.py` — generates `config/Modelfile.<base>-<persona>`
- `tools/lora/build_persona_models.sh` — creates Ollama tags for existing adapters
- `tools/lora/train_all_personas.sh` — trains, converts, and registers all adapters end-to-end
- `tools/lora/evaluate_persona.py` — golden-case evaluator
- `tests/golden_persona_cases.jsonl` — persona-specific behavioral checks

### Typical workflow

> **Note:** The pre-trained Michael LoRA artifacts and datasets were archived to `backups/v10-dev-cleanup/2026-07-04/lora/` as part of the v10-dev cleanup. The commands below regenerate them at their original paths from the built-in specs.

```bash
cd ~/lucy-v10
source ui-v10/.venv/bin/activate
python3 tools/lora/build_datasets.py
python3 tools/lora/train_persona_lora.py --dataset data/lora/datasets/michael.jsonl --base-tag local-lucy-llama31 --persona michael
HF_TOKEN=... python3 tools/lora/convert_adapters_to_gguf.py --adapter-dir models/lora/local-lucy-llama31/michael
ollama create local-lucy-llama31-michael -f config/Modelfile.local-lucy-llama31-michael
```

Or run the full pipeline:
```bash
HF_TOKEN=... tools/lora/train_all_personas.sh
```

Evaluate both LoRA and prompt-level paths:
```bash
# LoRA path (llama3.1)
python3 tools/lora/evaluate_persona.py --model local-lucy-llama31-michael --persona michael

# Prompt-level fallback path (qwen3 14B)
python3 tools/lora/evaluate_persona.py --model local-lucy --prompt-persona michael --persona michael
```

### Current adapter status

| Base tag | Backend model | Michael | Notes |
|---|---|---|---|
| `local-lucy-llama31` | Llama 3.1 8B | ⚠️ Archived | Artifacts backed up to `backups/v10-dev-cleanup/2026-07-04/lora/`; prompt fallback remains active |
| `local-lucy` / `local-lucy-fast` / `local-lucy-qwen3` | Qwen3 14B | ⚠️ Prompt fallback | OOM on RTX 3060 12 GB |
| `local-lucy-mistral` | Mistral-Nemo 12B | ⚠️ Prompt fallback | OOM on RTX 3060 12 GB |

### Hardware limitation: Qwen3 14B

`Qwen/Qwen3-14B` OOMs inside `prepare_model_for_kbit_training` even at rank 4 / seq 512 / batch 1 / 4-bit on the RTX 3060 12 GB. The Qwen3-based tags therefore use prompt-level persona injection at runtime. This is handled transparently by `_resolve_persona_model()` in `tools/router_py/local_answer.py`.

## Feedback Learning System

Local Lucy learns from natural-language user feedback.

| User says | Detected as | Action |
|---|---|---|
| "that was wrong, it should have been LOCAL" | Route correction | Logs correction → rebuilds embeddings |
| "that was a bad answer" | Negative quality | Logs complaint |
| "perfect, thank you" | Positive quality | Strengthens existing route |
| "forget that" | Retraction | Removes from memory |

**Files:**
- `tools/router_py/feedback_buffer.py` — Ring buffer of last 5 exchanges
- `tools/router_py/feedback_parser.py` — NL feedback detection
- `models/router/user_feedback.jsonl` — Logged corrections
- `models/router/background_learner.py` — Rebuilds embedding index

**Rule:** Set `LUCY_AUTO_LEARN=0` during development unless explicitly testing learner behavior.

---

## Common Footguns

1. **Two `current_state.json` locations** — HMI uses `~/.local/share/local-lucy/state/` (XDG) or legacy `~/.codex-api-home/lucy/runtime-v10/state/`. `START_LUCY.sh` sets the canonical path via `LUCY_RUNTIME_NAMESPACE_ROOT`.

2. **`PipelineContext` is frozen** — Use `dataclasses.replace()` to modify. Unknown keys from `context` dict merge into `.extras`.

3. **SQLite namespaces** — `StateManager` uses hostname-based namespaces by default, not `"default"`.

4. **`.env` writes are deprecated** — `execution_engine_state.py` no longer writes `.env` files. JSON + SQLite are canonical.

5. **HMI offscreen tests are standalone scripts** — Run directly: `QT_QPA_PLATFORM=offscreen python3 test_*.py`, not via `pytest`.

6. **No GPU in tests** — Low VRAM environment. Router tests use mocks.

---

## Operational Guardrails

1. **Sync only after tests pass.** Never push a dirty snapshot.
2. **Do not use `rsync --delete` unless explicitly approved.**
3. **Stop and ask before editing:** SQLite schema, router classification, HMI redesign, model retraining, launcher restructuring.

---

*End of instructions. Read `SESSION_CONTEXT.md` for live state.*
