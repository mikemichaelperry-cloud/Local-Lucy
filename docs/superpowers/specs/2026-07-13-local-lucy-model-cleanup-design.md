# Local Lucy v10/v11 Model Cleanup — Design Spec

**Date:** 2026-07-13
**Branch:** `v10-dev`
**Topic:** Remove all models except Gemma 4 and one fast Llama wrapper from Local Lucy's active universe, while leaving every installed Ollama tag available to the chess program.

---

## 1. Goal

Local Lucy currently exposes and routes to a multi-model local fleet (Qwen3, Mistral, and several `local-lucy-*` wrapper tags). The user wants the assistant restricted to:

- **Gemma 4** (`gemma4:12b-it-qat`), including the smart-routing bypass feature.
- **One fast Llama wrapper** (`local-lucy-llama31`, based on `llama3.1:8b`).

All other installed Ollama tags must remain installed so the standalone Ubuntu Chess program can continue to select them via Ollama's `/api/tags` endpoint. The cleanup is **hard-coded and surgical**: edit selectors, defaults, and references rather than adding a new config layer. No `ollama rm` commands are run.

---

## 2. Allowed model universe in Local Lucy

| Backend tag | Display label (HMI) | Notes |
|---|---|---|
| `auto` | "Auto (Lucy chooses per query)" | Shadow recommendations restricted to the allowed set. |
| `gemma4:12b-it-qat` | "gemma4:12b-it-qat (gemma4 12B reasoning/multimodal)" | Smart-routing bypass preserved. |
| `local-lucy-llama31` | "local-lucy-llama31 (llama3.1 8B)" | Default factual/local model. |

Removed from Local Lucy's active universe but kept in Ollama:

- `local-lucy` (Qwen3 14B base wrapper)
- `local-lucy-fast` (Qwen3 14B)
- `local-lucy-stable` (Llama 3.1 wrapper, but not the chosen fast Llama)
- `local-lucy-memory` / `local-lucy-mem` (Llama 3.1 wrapper, but not the chosen fast Llama)
- `local-lucy-qwen3` (Qwen3 14B)
- `local-lucy-mistral` (Mistral NeMo)
- `local-lucy-llama31-racheli` (persona variant; not the chosen fast Llama)
- `local-lucy-llama31-michael` (persona variant; not the chosen fast Llama)
- `local-lucy-michael` (Qwen3 persona wrapper)
- `local-lucy-mistral-michael` (Mistral persona wrapper)
- `local-lucy-fast-michael` (Qwen3 persona wrapper)
- `mistral-nemo`
- `qwen3:14b`
- `qwen3:30b`
- `llama3.1:8b` (raw base model; chess can use it, Local Lucy uses the wrapped `local-lucy-llama31`)

---

## 3. Files to change

### 3.1 HMI model selector
- **File:** `ui-v10/app/panels/control_panel.py`
- **Change:** Trim `_MODEL_LABELS` to contain only `auto`, `gemma4:12b-it-qat`, and `local-lucy-llama31`.
- **Reason:** This is the user-facing control panel; the user explicitly requested HMI reflection of the cleanup.

### 3.2 Runtime control CLI
- **File:** `tools/runtime_control.py`
- **Change:** Trim `set-model` `--value` choices to the same allowed backend tags.
- **Reason:** Prevents CLI/state-file from selecting a model Local Lucy no longer recognizes.

### 3.3 Automatic model selector
- **File:** `tools/router_py/model_selector.py`
- **Changes:**
  - Replace `_CAPABILITY_DEFAULTS` so every bucket resolves to `local-lucy-llama31` or `gemma4:12b-it-qat`.
  - Drop Qwen3/Mistral/Llama-persona branches in `select_model()` and `_competing_model()`.
  - Trim `_LATENCY_BUDGETS_MS` to the remaining models.
  - Keep `_query_bucket()` classification; only the model mapping changes.
- **Reason:** Auto mode must not silently route to a removed model.

### 3.4 Local answer / heartbeat / identity mapping
- **File:** `tools/router_py/local_answer.py`
- **Changes:**
  - Update `_MODEL_IDENTITIES` to only map allowed tags.
  - Verify default heartbeat target and fallback model strings use `local-lucy-llama31` or `gemma4:12b-it-qat`.
- **Reason:** Identity answers and keep-alive must target valid models.

### 3.5 Runtime bridge defaults
- **File:** `ui-v10/app/services/runtime_bridge.py`
- **Change:** Update `LUCY_MODEL`, `LUCY_LOCAL_MODEL`, and `LUCY_OLLAMA_MODEL` env defaults to `local-lucy-llama31`.
- **Reason:** Default env must not reference a removed model.

### 3.6 Request pipeline / main
- **Files:** `tools/router_py/main.py`, `tools/router_py/request_pipeline.py`
- **Change:** Audit and remove any hard-coded fallback references to removed tags (e.g., default model strings).
- **Reason:** Pipeline defaults must stay consistent with the allowed universe.

### 3.7 Modelfiles
- **Directory:** `config/`
- **Change:** Move the following Modelfiles to `config/quarantined/`:
  - `Modelfile.local-lucy`
  - `Modelfile.local-lucy-fast`
  - `Modelfile.local-lucy-stable`
  - `Modelfile.local-lucy-mem`
  - `Modelfile.local-lucy-qwen3`
  - `Modelfile.local-lucy-mistral`
  - `Modelfile.local-lucy-michael`
  - `Modelfile.local-lucy-mistral-michael`
  - `Modelfile.local-lucy-fast-michael`
- **Keep in place:**
  - `Modelfile.local-lucy-llama31`
- **Move to `config/quarantined/`:**
  - `Modelfile.local-lucy-llama31-michael` (persona variant of the allowed base, but persona variants are also removed from Local Lucy's active universe)
- **Reason:** Physical removal from `config/` prevents accidental creation of removed Ollama tags during rebuild scripts, while `quarantined/` preserves the prompts for future restoration.

### 3.8 Persona handling
- **Files:** Any persona resolution code (e.g., `tools/router_py/model_selector.py::_resolve_persona_model`, HMI persona controls)
- **Change:** Persona resolution must fall back to `local-lucy-llama31` for any active persona. The `-michael` and `-racheli` variants of the allowed base are removed from Local Lucy's active universe along with the Qwen/Mistral persona variants.
- **Reason:** Keeps the persona UI concept alive but constrains its output to the single allowed Llama wrapper.

### 3.9 Tests
- **Files:**
  - `tools/router_py/test_model_selector.py`
  - `tools/router_py/test_local_answer.py`
  - `ui-v10/tests/test_model_selector_offscreen.py`
  - Any golden/semantic regression files asserting removed-model output.
- **Changes:**
  - Update expectations to Gemma 4 / `local-lucy-llama31` only.
  - Add `tools/router_py/test_allowed_models_only.py` asserting:
    - `control_panel._MODEL_LABELS` keys equal `{ "auto", "gemma4:12b-it-qat", "local-lucy-llama31" }`.
    - `runtime_control.py` `set-model` choices equal the same set.
    - `model_selector.select_model()` never recommends a removed tag for representative queries.

---

## 4. Auto-selector behavior after cleanup

| Query signal | Route | Recommended model | Rationale |
|---|---|---|---|
| General / fast / memory / coding / reasoning | `LOCAL` | `local-lucy-llama31` | Single reliable default. |
| Deep-thought / complex analysis | `LOCAL` | `gemma4:12b-it-qat` | Use the reasoning model. |
| Factual/current (`NEWS`, `WEATHER`, `TIME`, `FINANCE`, `EVIDENCE`, `AUGMENTED`) | external → local synthesis | `local-lucy-llama31` | Factual synthesis default. |
| Gemma 4 selected + smart routing ON | `LOCAL` (bypass) | `gemma4:12b-it-qat` | Preserved existing behavior. |

---

## 5. Verification plan

1. **Ollama inventory unchanged:** `ollama list` still shows all previously installed tags (chess program unaffected).
2. **HMI selector trimmed:** Control panel model drop-down contains only Auto, Gemma 4, and `local-lucy-llama31`.
3. **CLI rejection:** `runtime_control.py set-model --value local-lucy-qwen3` exits with an error.
4. **Auto-selector tests:** `test_model_selector.py` passes with updated expectations.
5. **New regression test:** `test_allowed_models_only.py` passes.
6. **Targeted regression battery:** Re-run the suite from the 2026-07-13 handoff:
   ```bash
   cd /home/mike/lucy-v10
   python3 -m pytest \
     tools/router_py/test_gemma4_identity.py \
     tools/router_py/test_ollama_heartbeat_model_switch.py \
     tools/tests/test_gemma4_smart_routing_state.py \
     ui-v10/tests/test_gemma4_smart_routing_offscreen.py \
     tools/router_py/test_request_pipeline.py -q
   ```
7. **Live smoke test:** Start Local Lucy, confirm model selector shows only allowed tags, submit a query, confirm response is generated.

---

## 6. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Auto-selector loses Qwen3/Mistral-specific behavior | New policy maps every bucket to Gemma 4 / `local-lucy-llama31`; user has confirmed this is acceptable. |
| Hidden references to removed tags in scripts not yet read | Grep for removed tag names after code changes; update any stragglers. |
| Persona variants of removed base models still built by `build_modelfiles.py` | Do not change build scripts unless they are invoked automatically; move outputs to `quarantined/` if they recreate removed tags. |
| Chess program affected | Chess reads Ollama `/api/tags` directly; we do not run `ollama rm`, so it remains unaffected. Verify with `ollama list` before and after. |
| State file contains a removed model at startup | On first run after the change, if `current_state.json` has a removed model, runtime should fall back to `local-lucy-llama31` or auto. Verify behavior and document if needed. |

---

## 7. Out of scope

- Uninstalling models from Ollama.
- Changing the chess program.
- Adding a dynamic allowlist config file.
- Modifying LoRA training scripts beyond moving their output Modelfiles to `quarantined/`.
- Installing additional Gemma 4 variants; if more are installed later, they must be added to the allowlist explicitly.

---

*Approved for implementation planning.*
