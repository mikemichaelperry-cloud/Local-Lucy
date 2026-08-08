# Local Lucy v11 — Agent Instructions

> **READ `SESSION_CONTEXT.md` FIRST at every session start.**
> It contains the current branch, git state, environment variables, and latest changes.
> This file contains the rules; `SESSION_CONTEXT.md` contains the live state.

---

## Authority

- **Working root:** `/home/mike/lucy-v11`
- **Active branch:** `main`
- **Frozen:** V9 is tagged `local-lucy-v9-frozen-2026-05-28`. Never modify it.
- **Default model:** `local-lucy-llama31` (llama3.1:8b via Ollama)
- **Qualified models:** `local-lucy-llama31` and `local-lucy-gemma4` — see Qualification Status below. Other Ollama tags on the host (qwen3, mistral-nemo, `local-lucy-fast`, etc.) are legacy; nothing in the active code defaults to them.

---

## Qualification Status

**QUALIFIED on HEAD `8c80cdb`** (2026-08-07): STAGE_19 clean run 7/7, no dual-model residency.

- Programme docs live in `qualification/`: `TEST_MASTER_PLAN.md`, `RUNBOOK.md`, `DECISIONS.md`, `TEST_STATUS.json`, `COMPLETION_REPORT_2026-08-07_FINAL_REQUAL.md` (latest).
- Current desktop copies of the key docs live in `~/Desktop/Local Lucy V11/` (stale versions are in its `Local_Lucy_V11_Archive/`).
- **GPU rule:** the RTX 3060 12 GB can hold only one Local Lucy model. Never run model-bearing tests concurrently; the stage scripts enforce single-model residency sequentially.
- **Do not retrain** `models/router/classifier_head.pt` without first verifying against the frozen validation corpus.

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
| Router classification | Do not change the classifier head, embeddings, or keyword guard behavior without tests + frozen-corpus validation |
| SQLite schema | Do not modify `lucy_state.db` or `memory.db` schema |
| HMI redesign | Forbidden per user constraint |
| Model weights | Do not retrain or replace the embedding index without explicit instruction |
| Voice runtime | Do not modify the whisper.cpp / TTS backend integration in `tools/voice/` |
| Persona LoRA adapters | Training/conversion may be run when explicitly requested; safe to create tags and rerun build scripts |

**Allowed changes:**
- `tools/router_py/execution_engine/`, `execution_engine_state.py` — state persistence
- `tools/router_py/classify.py`, `classify_core/`, `policy_router/` — routing guards (with tests)
- `tools/router_py/payload_builders.py` — pure formatting
- Tests in `tools/router_py/test_*.py`, `tools/tests/`, and `ui-v10/tests/test_*.py`
- Documentation, config, scripts, CI

---

## Key Files

| File | Role | Touch with care |
|------|------|-----------------|
| `tools/router_py/main.py` | Entry point | Yes — keep request_id contract |
| `tools/router_py/request_pipeline.py` | Pipeline choke point | Yes — frozen dataclass contract |
| `tools/router_py/execution_engine/` | Dispatcher package (`__init__.py`, `helpers.py`) | Yes — all routes must write state |
| `tools/router_py/execution_engine_state.py` | StateWriter (JSON + SQLite) | Yes — public API must not break |
| `tools/router_py/classify.py` + `classify_core/` + `policy_router/` | Intent classification + guards | Yes — add tests for new guards |
| `tools/router_py/local_answer.py` + `local_answer_core/` | Local-answer engine, self-knowledge, persona injection | Yes |
| `tools/router_py/model_selector.py` | Model + persona-model resolution | Yes |
| `tools/memory/memory_service.py` | Persistent/session memory, retrieval knobs | Yes — see env knobs below |
| `tools/router_py/payload_builders.py` | Shared pure payload builders | Yes — both routers depend on this |
| `tools/router_py/request_types.py` | Centralized frozen dataclasses | Yes — schema changes ripple |
| `ui-v10/app/services/state_store.py` | HMI reads JSON state | No — read-only per constraints |
| `ui-v10/app/panels/status_panel.py` | HMI displays state | No — read-only per constraints |
| `ui-v10/app/backend/*.py` | **RE-EXPORT WRAPPERS ONLY** | Never add logic here |

**Critical:** `ui-v10/app/backend/*.py` are 3–9 line wrappers. Edit `tools/router_py/` and let wrappers pick it up. This has been a repeated footgun.

Note: several former single-file modules are now packages — `execution_engine.py` → `execution_engine/`, `feedback_parser.py` → `feedback_parser/`. Check for the package before editing a `.py` path from an older doc.

---

## Environment Variables

```bash
LUCY_ROOT=~/lucy-v11                    # Project root
LUCY_RUNTIME_NAMESPACE_ROOT=~/.local/share/local-lucy-v11   # XDG data dir (code default)
LUCY_RUNTIME_AUTHORITY_ROOT=~/lucy-v11  # Code authority validation
LUCY_UI_ROOT=~/lucy-v11/ui-v10          # HMI path
LUCY_OLLAMA_API_URL=http://127.0.0.1:11434/api/generate
LUCY_LOCAL_MODEL=local-lucy-llama31     # Code default if unset
LUCY_AUTO_LEARN=0                       # Set 0 during development to prevent mutation
                                        # (effective default is ON via runtime_control.py)

# Memory retrieval knobs (tools/memory/memory_service.py; shown with code defaults)
LUCY_MEMORY_RECENT_TURN_LIMIT=12        # verbatim recent turns injected
LUCY_MEMORY_MAX_INJECTED_TURNS=8        # semantic older turns
LUCY_MEMORY_MAX_CHARS=2000              # memory context budget (execution engine passes 2400)
LUCY_MEMORY_SIMILARITY_THRESHOLD=0.70
LUCY_MEMORY_TOPIC_SHIFT_THRESHOLD=0.50  # explicit recall queries bypass topic-shift gating
LUCY_SESSION_MEMORY=1                   # enable session-memory injection (HMI memory toggle sets this)

# Diagnostics
LUCY_ROUTER_DIAGNOSTICS=1               # lightweight routing trace
```

`LUCY_ROUTER_PY` / `LUCY_EXEC_PY` are dead — nothing reads them; do not reintroduce.

---

## Test Commands

```bash
# Full router suite (CPU only, mocks; ~2min)
cd ~/lucy-v11
source ui-v10/.venv/bin/activate
python -m pytest tools/router_py/ -q

# HMI offscreen tests (standalone scripts, not pytest)
QT_QPA_PLATFORM=offscreen python3 ui-v10/tests/test_comprehensive_hmi_inspection.py

# Qualification profiles — see qualification/RUNBOOK.md
python3 qualification/run_full_qualification.py --no-production-data   # full programme, resumable
python3 tools/router_py/stage_19_clean_run.py                          # final clean run (GPU, ~18min)

# Live end-to-end (single request, uses GPU model)
python3 -c "import sys; sys.path.insert(0,'tools'); from router_py.main import execute_plan_python; \
  r = execute_plan_python('What is 2+2?', timeout=30); print(r.status, r.route)"
```

**GPU discipline:** model-bearing stage scripts (08–13, 16, 19) load Gemma/Llama onto the RTX 3060. Run them sequentially, never in parallel, and check `curl -s localhost:11434/api/ps` is empty first.

---

## Persona System

The runtime supports user-specific personas (e.g. Michael). Two mechanisms:

1. **Prompt-level injection** — `tools/router_py/local_answer_core/self_knowledge.py` loads `config/personas/<name>.txt` and injects it after the self-knowledge block. Currently only `michael.txt` exists (a `racheli` fragment is missing — known gap; her LoRA tag exists).
2. **Model-level LoRA adapters** — `tools/router_py/model_selector.py` (`_resolve_persona_model`) maps `{base}-{persona}` to an installed Ollama tag when the base is in `_ALLOWED_PERSONA_BASES` (`local-lucy-llama31`, `local-lucy-gemma4`); otherwise it falls back to base model + prompt fragment. Installed persona tags: `local-lucy-llama31-michael`, `local-lucy-llama31-racheli`.

LoRA pipeline (dormant but intact) in `tools/lora/`: `build_datasets.py`, `train_persona_lora.py`, `convert_adapters_to_gguf.py`, `build_modelfiles.py`, `build_persona_models.sh`, `train_all_personas.sh`, `evaluate_persona.py`. QLoRA training only fits Llama-3.1-8B on the RTX 3060 12 GB; larger bases (Qwen3-14B, Mistral-Nemo-12B) OOM and are not part of the active model set.

---

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
- `tools/router_py/feedback_parser/` — NL feedback detection package (parser, patterns, learner, logger)
- `models/router/user_feedback.jsonl` — Logged corrections
- `models/router/background_learner.py` — Rebuilds embedding index (medical/vet/finance/legal feedback goes to `pending_review.jsonl` for human review)

**Rule:** Set `LUCY_AUTO_LEARN=0` during development unless explicitly testing learner behavior. The effective default is ON (`runtime_control.py`), so this matters.

---

## Common Footguns

1. **Single `current_state.json` location** — The canonical state directory is `~/.local/share/local-lucy-v11/state/` (`memory.db`, `lucy_state.db`, `current_state.json`, ...). `START_LUCY.sh` sets `LUCY_RUNTIME_NAMESPACE_ROOT` to this path; explicit overrides still win. Legacy namespaces (`~/.local/share/local-lucy/`, `lucy-v10/`, ...) still exist on disk — do not read from them.

2. **`PipelineContext` is frozen** — Use `dataclasses.replace()` to modify. Unknown keys from `context` dict merge into `.extras`.

3. **SQLite namespaces** — `StateManager` uses hostname-based namespaces by default, not `"default"`.

4. **`.env` writes are deprecated** — `execution_engine_state.py` no longer writes `.env` files. JSON + SQLite are canonical.

5. **HMI offscreen tests are standalone scripts** — Run directly: `QT_QPA_PLATFORM=offscreen python3 test_*.py`, not via `pytest`.

6. **CPU tests mock; GPU tests are sequential** — Router/unit tests mock the model. Stage scripts use the real GPU models and must run one at a time (see GPU discipline above).

7. **Scenario suites record `response_text`** — When a stage-09/11 scenario fails, check `qualification/results/stage_*_scenarios.json` for the captured model response before suspecting retrieval; literal-substring concept checks can flake on model phrasing (see DEC-016).

---

## Operational Guardrails

1. **Sync only after tests pass.** Never push a dirty snapshot.
2. **Do not use `rsync --delete` unless explicitly approved.**
3. **Stop and ask before editing:** SQLite schema, router classification, HMI redesign, model retraining, launcher restructuring.

---

*End of instructions. Read `SESSION_CONTEXT.md` for live state.*
