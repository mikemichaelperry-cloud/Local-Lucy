# Gemma 4 Smart Routing + Low-VRAM Warning — Design Spec

**Date:** 2026-07-12
**Status:** Draft — awaiting review
**Author:** Kimi Code (with user review)

---

## Goal

Add an optional "smart routing" mode for Gemma 4 that lets the model handle intent/routing internally, bypassing Local Lucy’s embedding/intent/router layers while preserving deterministic fast paths and showing a VRAM warning on low-VRAM GPUs.

---

## Motivation

Gemma 4 12B has a native system role, structured-output support, and strong zero-shot instruction following. For short, ordinary conversations it can reliably decide what kind of answer to give without the hybrid embedding router, policy keyword gates, or intent classifier. Skipping those layers reduces latency and lets Gemma 4’s own reasoning shape the response.

At the same time, Gemma 4 is a large model. On GPUs with 12 GB VRAM it fits, but only if other VRAM-hungry components are unloaded. The UI should warn the operator when VRAM is tight.

---

## User-visible behavior

### 1. HMI toggle

- A new checkbox in the Engineering HMI: **"Gemma 4 Smart Routing"**.
- Default: **off**.
- Only enabled when the selected local model is a Gemma 4 tag (`gemma4:*`).
- Persisted in `current_state.json` under `gemma4_smart_routing` (boolean).

### 2. When smart routing is ON

For any request whose active local model is Gemma 4:

1. **Explicit prefixes win immediately:**
   - `news:` → `NEWS` route (no LLM).
   - `evidence:` / `augmented:` → `EVIDENCE` / `AUGMENTED` route.
2. **Deterministic fast paths still run:**
   - Existing news-pattern detection → `NEWS`.
   - Existing evidence/augmented triggers → `EVIDENCE` / `AUGMENTED`.
3. **Everything else → `LOCAL` with Gemma 4**, skipping:
   - `classify_intent()`
   - `select_route()` (embedding router, policy keyword gates, LLM arbiter)

When smart routing is OFF, the full existing router stack runs unchanged.

### 3. VRAM warning

When the user selects a `gemma4:*` model, the HMI reads available VRAM. If free VRAM is < 12 GB, a non-blocking warning is shown:

> Gemma 4 12B may be tight on this GPU. Short conversations and single-model operation are fine; long context or concurrent models may hit VRAM limits. Ollama can fall back to system RAM if needed, but responses will be slower.

The warning does not block selection; it is informational.

---

## What stays intact

- **News route:** explicit prefix and pattern-based fast path remain.
- **Evidence/Augmented route:** explicit prefix and existing triggers remain.
- **Execution-engine guardrails:** tool authorization, file-system permissions, and any keel/policy checks that happen inside the execution engine remain.
- **Non-Gemma models:** the toggle has no effect; they use the full router stack.

---

## Architecture

### Components touched

| Component | Change |
|---|---|
| `ui-v10/app/panels/control_panel.py` | Add `gemma4_smart_routing` checkbox; enable/disable based on selected model. |
| `ui-v10/app/services/runtime_bridge.py` | Persist `gemma4_smart_routing` to `current_state.json`; read it back into env. |
| `tools/router_py/request_pipeline.py` | In `process()`, check the bypass flag and model family before calling classifier/router. |
| `tools/router_py/local_answer.py` | VRAM helper for HMI warning (reusable). |

### Data flow (smart routing ON)

```
request → execute_plan_python()
              │
              ▼
        explicit route prefix? ──yes──► NEWS / EVIDENCE / AUGMENTED
              │ no
              ▼
        deterministic fast path? ──yes──► NEWS / EVIDENCE / AUGMENTED
              │ no
              ▼
        gemma4 smart routing ON? ──yes──► LOCAL (Gemma 4)
              │ no
              ▼
        full classifier/router stack
```

---

## VRAM detection

The HMI will detect available VRAM using one of these methods, in order of preference:

1. `pynvml` (NVIDIA Management Library) if installed.
2. `nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits` subprocess.
3. Fallback: no warning if detection fails.

Only a warning is shown; selection is not blocked.

---

## CPU / RAM fallback and crash-proofing

Ollama/llama.cpp already supports CPU offloading when a model does not fit entirely in VRAM. Local Lucy must not force GPU-only execution for Gemma 4. Requirements:

1. **No GPU-only options** in Local Lucy’s Ollama payload for Gemma 4 (e.g., do not set `num_gpu` to all layers if it would crash on low-VRAM GPUs).
2. **Graceful degrade:** if Ollama returns an out-of-memory or model-load error, Local Lucy must catch it, log it, and return a readable error message instead of crashing the HMI or pipeline.
3. **Allow system RAM usage:** if VRAM is exhausted, Ollama should offload layers to system RAM automatically. Local Lucy will not block this.
4. **HMI warning updated:** the low-VRAM warning should note that CPU/RAM fallback may be used, but performance will be slower.

---

## Configuration / state

```json
{
  "model": "gemma4:12b-it-qat",
  "gemma4_smart_routing": true
}
```

Environment variable override for testing: `LUCY_GEMMA4_SMART_ROUTING=1|0`.

---

## Testing

- **Unit:** bypass logic in `request_pipeline.py` with flag on/off and Gemma/non-Gemma models.
- **Integration:** HMI toggle persists and restores correctly.
- **Regression:** full `make test` with toggle off (default) must still pass.
- **Manual:** with toggle on, verify:
  - `news: latest Israel` uses news route.
  - `evidence: ...` uses evidence route.
  - ordinary questions go straight to LOCAL Gemma 4.
  - VRAM warning appears on 12 GB GPU and not on 24 GB GPU.

---

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Bypassing policy gates lets Gemma 4 answer sensitive topics. | Toggle is off by default; hard execution-engine gates remain; news/evidence fast paths are preserved. |
| VRAM warning spams users. | Show once per model selection, dismissible, non-blocking. |
| Non-deterministic routing. | Document that smart routing trades deterministic routing for lower latency; default remains deterministic. |

---

## Open questions

1. Should the VRAM threshold be configurable (e.g., env var `LUCY_GEMMA4_VRAM_WARN_GB=12`) or hard-coded?
2. Should smart routing also bypass the model selector’s capability bucketing, or keep it so Gemma 4 can still be selected via `select_model()` for specific tasks?
3. Should the bypass log its decisions to `router_decisions.jsonl` for auditability?

---

## Approval

Pending user review.
