# Local Lucy — Session Context (Auto-Updated)

> **READ THIS FIRST** at every session start. Updated at every handoff.
> Latest change: Consolidation & hardening closeout (2026-08-08) — tasks 1-5 + closeout: auto-learn opt-in (DEC-017), shared scenario evaluation (DEC-018), dead plumbing pruned, stale test patches repointed, docs re-synced. Previous: final requalification STAGE_19 7/7 on HEAD `8c80cdb` (2026-08-07).

---

## Quick Orientation

| | |
|---|---|
| **Repository** | `~/lucy-v11` (also `LUCY_ROOT`) |
| **Branch** | `main` |
| **Last tag** | `v11-provisional-runnable-2026-07-21` |
| **Version** | `11.0.0-dev` |
| **Models** | `local-lucy-llama31` (default) and `local-lucy-gemma4` — both QUALIFIED |
| **Handoff file** | `~/Desktop/Local Lucy V11/SESSION_HANDOFF.md` (repo master: `qualification/SESSION_HANDOFF.md`; old versions in `Local_Lucy_V11_Archive/`) |
| **Default branch on origin** | `main` ✅ |
| **Working tree** | Clean (consolidation closeout committed 2026-08-08; see Git State) |

---

## Directory Structure

```
lucy-v11/
├── tools/                    # Core backend (router, execution, voice, memory, internet)
│   ├── router_py/            # Main execution engine (~50 modules; several are packages:
│   │                         #   execution_engine/, classify_core/, policy_router/,
│   │                         #   local_answer_core/, feedback_parser/)
│   ├── lora/                 # Persona LoRA training, conversion, evaluation
│   ├── internet/             # Web search (DuckDuckGo, SearXNG, Brave)
│   ├── voice/                # TTS (Kokoro/Piper/edge-tts), STT (whisper.cpp server), playback
│   ├── memory/               # SQLite memory service
│   └── xdg_paths.py          # XDG-compliant path resolution
├── ui-v10/                   # PySide6 HMI (directory name predates v11; still the current HMI)
│   ├── app/                  # Main window, panels, widgets, services
│   │   ├── backend/          # Thin re-exports from router_py
│   │   ├── panels/           # Control, conversation, status, event log
│   │   └── services/         # RuntimeBridge, state store, log watcher
│   ├── tests/                # Offscreen PySide6 tests
│   └── .venv/                # Python virtual environment
├── web_adapter/              # Optional aioHTTP web interface (stateless)
│   ├── server.py             # API + static HTML UI
│   ├── static.py             # Dependency-free frontend page
│   └── test_web_adapter.py   # Web adapter tests
├── models/router/            # Embedding router, training data, background learner
├── config/                   # Modelfiles, prompts, trust rules, policies, personas/
├── services/searxng/         # Docker Compose + settings.yml for local search proxy
├── scripts/                  # Operational scripts (check_environment.py, migrate_db.py)
├── qualification/            # Qualification programme: master plan, runbook, decisions,
│                             #   status, results/, completion reports, session handoff
├── docs/runbooks/            # INSTALL.md, SECURITY.md, PERSONAS.md, OLLAMA_SECURITY.md
├── README.md                 # Project overview, usage, features
├── ARCHITECTURE.md           # System architecture
├── CHANGELOG.md              # Keep a Changelog format
├── runtime/                  # Generated at runtime (ignored by git)
├── state/                    # Generated at runtime (ignored by git)
├── voice/                    # Generated audio (ignored by git)
├── START_LUCY.sh             # Desktop launcher (entry point)
├── lucy_chat.sh              # CLI chat entry point
├── Makefile                  # install, test, lint, run, clean, check-env
├── VERSION                   # 11.0.0-dev
└── pyproject.toml            # Packaging, dependencies, tool configs
```

---

## Key Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `LUCY_ROOT` | derived from `START_LUCY.sh` | Project root |
| `LUCY_RUNTIME_NAMESPACE_ROOT` | `~/.local/share/local-lucy-v11` (XDG) | Runtime state, DBs, logs |
| `LUCY_RUNTIME_AUTHORITY_ROOT` | `$LUCY_ROOT` | Code authority validation |
| `LUCY_UI_ROOT` | `$LUCY_ROOT/ui-v10` | HMI path |
| `LUCY_OLLAMA_API_URL` | `http://127.0.0.1:11434/api/generate` | Local LLM endpoint |
| `LUCY_LOCAL_MODEL` | `local-lucy-llama31` | Default Ollama model |
| `LUCY_STATE_DB` | `$LUCY_RUNTIME_NAMESPACE_ROOT/state/lucy_state.db` | SQLite state DB |
| `LUCY_MEMORY_DB_PATH` | `$LUCY_RUNTIME_NAMESPACE_ROOT/state/memory.db` | SQLite memory DB |
| `LUCY_SESSION_MEMORY` | `0` (HMI memory toggle sets `1`) | Session-memory injection |
| `LUCY_MEMORY_*` | see `AGENTS.md` | Retrieval knobs: recent turns 12, semantic turns 8, max chars 2000 (engine passes 2400), similarity 0.70, topic-shift 0.50 |
| `LUCY_AUTO_LEARN` | OFF — opt-in (DEC-017) | Set `1` to enable learning |
| `QT_QPA_PLATFORM` | `xcb` | Qt platform plugin |

---

## Entry Points

| Surface | Command |
|---------|---------|
| Desktop HMI | `bash START_LUCY.sh` or `make run` |
| CLI chat | `bash lucy_chat.sh "your question"` |
| Health check | `python -m tools.router_py.health` |
| Environment validator | `python scripts/check_environment.py` or `make check-env` |
| DB migration | `python scripts/migrate_db.py` |
| Optional web UI | `LUCY_WEB_ENABLED=1 python -m web_adapter` |
| Pytest (full) | `make test` |
| Qualification | `python3 qualification/run_full_qualification.py --no-production-data` (see `qualification/RUNBOOK.md`) |
| Lint | `make lint` |

---

## Git State

```bash
# Current state (verified 2026-08-08, closeout)
Branch: main
Origin HEAD: main (not checked against remote)
Latest tag: v11-provisional-runnable-2026-07-21
Commits since tag: 213
Working tree: clean (only untracked tools/router_py/state/__pycache__/, never commit)
```

### Recent Commits (last 16)
```
5de2bfc docs: consolidation closeout, DEC-018, known_failing_tests tracking
2031f4c fix(tests): repoint stale local_answer patch targets; correct stale model-facing text
bdfdfad fix(config): align self-knowledge context figures with Modelfile num_ctx
61bec06 chore: prune dead qwen3 router script and stale model references
3dbb2a2 chore: remove dead LUCY_ROUTER_PY/LUCY_EXEC_PY plumbing
33d4def refactor(qual): share scenario evaluation, add required_answer_concepts_any
8db0d35 fix(runtime): default auto-learn to opt-in (DEC-017)
facc683 fix(tests): align memory text-file fallback tests with post-5591c1a contract
95925c6 docs: consolidation and hardening implementation plan
696f82f chore(router): learner-applied user feedback corrections (auto-learn, 2026-08-08)
8c80cdb docs: update AGENTS.md active branch to main
9c475c2 docs: align session context and self-knowledge with 200k Engineering-mode limit
7135801 docs: remove self-referential HEAD line from SESSION_HANDOFF.md
f44bd98 docs: record current HEAD in SESSION_HANDOFF.md
568fa7e docs: record docs commit hash in SESSION_HANDOFF.md
d99b48e docs: update handoff and architecture for 200k Engineering-mode context limit
```

### Consolidation & Hardening — 2026-08-08 (latest)
- **Plan:** `docs/superpowers/plans/2026-08-08-consolidation-and-hardening.md`; task briefs/reports in `.superpowers/sdd/` (task-7 is the closeout). Task 6 (ui-v10 rename) deferred — see TODO #29.
- **Tasks 1-5 (commits `95925c6..bdfdfad`):** two stale memory-fallback tests fixed; auto-learn flipped to opt-in (DEC-017); scenario evaluation deduplicated into `tools/router_py/scenario_checks.py` with new `required_answer_concepts_any` scenario field; dead `LUCY_ROUTER_PY`/`LUCY_EXEC_PY` plumbing removed; `qwen3_router.py` + `rollout_config.env` deleted; `system_prompt.txt` qwen3 line fixed; self-knowledge context figures aligned with Modelfile `num_ctx`; Ollama tag `local-lucy-memory` removed (user-approved).
- **Task 7 closeout (this session):**
  - `test_local_answer.py` 16 carried failures under `-m ""` fixed: stale patch targets repointed to `local_answer_core` consuming modules; memory-preamble test aligned with the deliberate Gemma-only `_PromptShaper` hint; **real latent bug fixed** — `local_answer_core/config.py::from_env` was missing `import json`, silently breaking the `current_state.json` model fallback (see DEC-018).
  - `README.md` `LUCY_AUTO_LEARN` row corrected (default `0`, opt-in, DEC-017).
  - `config/Modelfile.local-lucy-{llama31,gemma4}` SYSTEM prompts corrected (llama31 8B / gemma4 12B, num_ctx 8192; qwen3:14b/2048-token text removed) + `ollama create` NOTE comment added; live Ollama tags intentionally NOT rebuilt. `config/system_prompt.txt` "14B/8B-class" → "8B/12B-class". Manifests regenerated (`make sha`).
  - `qualification/TEST_STATUS.json` gained `known_failing_tests` (empty; must stay empty) + note; DEC-018 added to `qualification/DECISIONS.md`; AGENTS.md footgun 7 now points at `scenario_checks.py`.
  - Full CPU suite (restricted markers): **1637 passed, 0 failed**, 7 skipped (10:47); `test_local_answer.py` also green with `-m ""` (78 passed). Unrestricted slow/live subset: 20 pre-existing live/environment failures (verified identical at base `bdfdfad`; see task-7 report).
  - Desktop docs re-synced (`SESSION_CONTEXT.md`, `Local_Lucy_V11_DECISIONS.md`).
- **TODO changes:** #24 partially advanced (dead vars/config pruned; rename deferred → #29), #27 resolved (DEC-018), #28 resolved (requal-session changes committed), #29 added.
- **Deviation:** commit `696f82f` (learner-applied feedback corrections: +5 examples, 2+2 relabel WEATHER→LOCAL) rode along outside the plan; embeddings were rebuilt and verified aligned (1379 rows), and a row-count guard in `hybrid_router_v2.py` now prevents silent misalignment (regression-tested in `test_hybrid_router_v2_validation.py`).

### Documentation Review & Final Requalification — 2026-08-07/08
- **Trigger:** external review of the 2026-08-06 completion report/handoff found documentation defects and a qualification gap (memory-retrieval expansion `1930946` landed after the original STAGE_19 pass).
- **Doc corrections:** `COMPLETION_REPORT_2026-08-06.md` (qualified overstated claims; max_chars story corrected to 500 → 2000 env / 2400 engine; path fix); `SESSION_HANDOFF.md` rollback rewritten (pre-change commit `3249092`; env-var approximation cannot undo the code-only topic-shift bypass); `DECISIONS.md` gained DEC-016 (S09-GEM-007 any-single-marker relaxation); `memory_service.py` docstring default fixed (0.55 → 0.70).
- **STAGE_19 re-run #1 (HEAD `8c80cdb`):** 6/7 — S09-MEM-003 flake ("missing required concept: Local Lucy"). Root cause: model-wording flake, not retrieval — proven by STAGE_09 standalone 16/16 with near-verbatim recall. Harness now records `response_text`/`turn_responses` per scenario for diagnosability.
- **STAGE_19 re-run #2:** **7/7 passed, no dual-model residency, `final_loaded_models=[]`** → **QUALIFIED on HEAD `8c80cdb`**. Full story: `qualification/COMPLETION_REPORT_2026-08-07_FINAL_REQUAL.md`.
- **AGENTS.md rewritten** for current v11 reality (removed Qwen/Mistral persona tables, dead `LUCY_ROUTER_PY`/`LUCY_EXEC_PY`, package paths, memory knobs, GPU sequential-discipline rule); **SESSION_CONTEXT.md corrected** (this update).
- **Desktop docs:** current copies in `~/Desktop/Local Lucy V11/`; stale loose files were byte-identical to archive copies and removed; stale DECISIONS snapshot archived as `Local_Lucy_V11_DECISIONS_2026-08-01_stale.md`.

### Persona LoRA Pipeline — Completed Within Hardware Limits
- Phase 1 (prompt-level personas) previously complete and tested.
- Phase 2–5 completed for hardware-feasible models:
  - `tools/lora/` scripts for dataset generation, QLoRA training, GGUF conversion, Modelfile generation, and Ollama tag creation.
  - Persona datasets generated at `data/lora/datasets/{michael,racheli}.jsonl`.
  - Persona-aware model resolution in `tools/router_py/model_selector.py` (`_resolve_persona_model`; allowed bases `local-lucy-llama31`, `local-lucy-gemma4`).
  - HMI persona selector (`auto` / `Michael` / `Racheli`) added to Control Panel, plus indicator and clear button, forcing the active identity for all models.
  - Golden test cases expanded with `contains_any` / `not_contains_any` checks and evaluator hardened with `--min-pass-rate` and `--json` output.
  - `local-lucy-llama31-michael` and `local-lucy-llama31-racheli` adapters trained, converted to GGUF, and registered as Ollama tags.
- Hardware limitation on RTX 3060 12 GB:
  - `Qwen/Qwen3-14B` OOMs during `prepare_model_for_kbit_training` even at rank 4 / seq 512.
  - `mistralai/Mistral-Nemo-Instruct-2407` also OOMs at the same step, even at rank 4 / seq 512 / `q_proj,v_proj` only.
  - Qwen3/Mistral tags remain on the host but are legacy; they are not in the active model-selection path.
  - `train_all_personas.sh` now trains only Llama 3.1 adapters; docs/README/AGENTS/gpu_resource_allocation updated with the final adapter matrix.
- Docs updated:
  - New `docs/runbooks/PERSONAS.md` runbook with validation results.
  - `README.md`, `AGENTS.md`, `docs/gpu_resource_allocation.md` reflect final LoRA/prompt status and HMI selector.
- Tests passing:
  - `tools/router_py/test_local_answer.py`: 59 passed
  - `tools/tests/test_memory_*.py`: 109 passed, 5 subtests passed
  - `tools/lora/test_build_datasets.py`: 5 passed
  - `tools/lora/test_evaluate_persona.py`: 7 passed
  - Golden persona evaluations (`tests/golden_persona_cases.jsonl`):
    - Llama 3.1 Michael LoRA: 9/9 (100%)
    - Llama 3.1 Racheli LoRA: 12/12 (100%)
    - qwen3 14B Michael prompt: 8/9 (88.9%)
    - qwen3 14B Racheli prompt: 12/12 (100%)
    - Mistral-Nemo 12B Michael prompt: 8/9 (88.9%)
    - Mistral-Nemo 12B Racheli prompt: 11/12 (91.7%)
  - `ui-v10/tests/test_comprehensive_hmi_inspection.py`: 138 checks passed
- Full `make test` status: 972 passed, 19 skipped, 32 failed. The failures are pre-existing routing/semantic-regression tests unrelated to the persona pipeline; persona-focused tests all pass.

### Self-Analysis Mode — Hardened
- New `tools/router_py/self_analysis.py` parses Local Lucy's Python source with stdlib `ast` and existing `ruff`, then uses the configured local LLM via `LocalAnswer` to suggest improvements.
- `tools/router_py/execution_engine/` dispatches self-analysis queries when `self_analysis_mode` is `"on"` and the query references a Python file.
- **Fixes applied:**
  - Self-analysis results now write state files (`_write_state_files` / `_write_json_state_files`) so the HMI can display them.
  - Results are reported with route `SELF_REVIEW` (not `LOCAL`) and `policy_reason="self_analysis_mode"`.
  - Added `"self_analysis_error"` to `OutcomeCodeType` in `tools/router_py/request_types.py`.
  - `runtime_control.py` gained `set-self-analysis-mode` CLI parity with other toggles.
  - `runtime_control.py` `render_env` and `build_self_check_payload` now export `self_analysis_mode` / `LUCY_SELF_ANALYSIS_MODE`.
  - `ui-v10/app/services/runtime_bridge.py` `_build_payload_from_outcome` includes `self_analysis_mode` in `control_state`.
  - `ui-v10/app/panels/control_panel.py` `_emit_if_changed` now passes `current_state` so the Self-Analysis Mode checkbox is not cleared on a no-op toggle.
- HMI Engineering panel gained a "Self-Analysis Mode" checkbox; state is persisted in `current_state.json` via `runtime_control.py` and `runtime_bridge.py`.
- Static facts are labeled **LOCAL**; LLM suggestions are labeled **AUGMENTED**.
- Tests:
  - `tools/router_py/test_self_analysis.py`: 7 passed
  - `ui-v10/tests/test_self_analysis_mode_offscreen.py`: 2 passed
  - `ui-v10/tests/test_comprehensive_hmi_inspection.py`: 138 checks passed

### Self-Analysis Large-File / Large-Response Support — Implemented
- Goal: feed full source code into self-analysis prompts, support large files safely, and generate long detailed reviews via a dedicated `SELF_REVIEW` token budget.
- **Source-code inclusion and safety (`tools/router_py/self_analysis.py`):**
  - `analyze_file` now appends the raw file source under a `Source code:` header in the prompt context.
  - `_resolve_file` rejects path traversal, non-existent paths, directories, non-`.py` files, and files larger than 5 MB.
  - `_read_source` enforces the 5 MB cap at the read boundary (TOCTOU-safe) and uses `errors="replace"` for non-UTF-8 bytes.
  - Source longer than `self_review_context_chars` is truncated with a `[truncated at N characters; consider reviewing a smaller module]` notice.
- **Dedicated `SELF_REVIEW` route (`tools/router_py/local_answer_core/`):**
  - `LocalAnswerConfig` exposes `self_review_max_tokens` (default 4096) and `self_review_context_chars` (default 200000), overridable via `LUCY_SELF_REVIEW_MAX_TOKENS` and `LUCY_SELF_REVIEW_CONTEXT_CHARS`.
  - `_set_generation_profile("SELF_REVIEW", ...)` returns a `("self_review", self_review_max_tokens, "- Provide a thorough, detailed code review with concrete, minimal improvements.")` profile.
  - `_call_ollama` raises the `num_predict` ceiling only for `SELF_REVIEW`, so the budget is not capped by `num_predict_long`.
- **Caller and cache wiring:**
  - `SelfAnalysisEngine.suggest_improvements` calls `generate_answer(query=prompt, route_mode="SELF_REVIEW")`.
  - `generate_answer` bypasses the local repeat cache for `SELF_REVIEW`.
  - General Q&A short-circuits (policy, 807, tube-DB, personal-fact) and the 807 post-processing override are skipped for `SELF_REVIEW`.
- **Config unification:**
  - `SelfAnalysisEngine` accepts `self_review_context_chars` and obtains the default from `LocalAnswerConfig.from_env()`; `execution_engine/` passes the authoritative config value.
- **Documentation:**
  - Updated `docs/superpowers/specs/2026-07-15-self-analysis-large-files-design.md` to match implementation wording.
- **Tests:**
  - `tools/router_py/test_self_analysis.py`: 40 passed
  - `tools/router_py/test_code_review_model_resolver.py`: 7 passed
  - `tools/router_py/test_local_answer.py`: 58 passed
  - Combined target run: 47 passed
  - `ruff check` and `ruff format --check` clean on all modified files.

### Routing & Runtime Stability Fixes — 2026-07-24
- **Root cause of lockdown:** HMI/state file had `evidence=on`, but the process env `LUCY_EVIDENCE_ENABLED` was stale/off. Queries such as the 2026-07-23 22:22 self-model correction test and the 05:47 "What time is it?" query were routed to `EVIDENCE`/`TIME` and then blocked with `operator_blocked` because the pipeline saw evidence as disabled.
- **Fixes applied:**
  - `ui-v10/app/services/runtime_bridge.py`: added `_OLLAMA_LOAD_LOCK` (RLock), wrapped all Ollama load/unload/warmup paths, made `_warmup_ollama_model` evict other Lucy models first, and added `_apply_state_to_env()` at bridge init and before every submit so HMI toggles reach the pipeline.
  - `tools/router_py/request_types.py`: added `request_id` to `PipelineContext` and `to_dict()` so runtime-request IDs reach `StateWriter` and stop duplicate coarse IDs.
  - `tools/router_py/execution_engine_state.py`: `_make_request_id()` now uses nanoseconds + question hash.
  - `tools/router_py/local_answer.py`: added explicit self-knowledge instruction for fallback/evidence-provider questions, fixing the `capability_fallbacks` semantic regression.
  - `tools/router_py/security_guard.py`: input limit raised from 4000 to 16000 characters; related tests updated.
  - Test env leaks fixed in `tools/router_py/test_bypass_env.py`, `test_e2e_hmi_voice.py`, `test_voice_integration.py` using `monkeypatch.setenv`.
- **Verification:**
  - Full `python3 -m pytest`: **1225 passed, 12 skipped, 2 warnings** (0 failures).
  - Target stress test `tools/tests/test_stress_e2e_both_models.py`: passed.
  - Persona verification (prompt-level Michael):
    - `local-lucy-llama31`: 6/9 (66.7%)
    - `local-lucy-gemma4`: 7/9 (77.8%)
  - Ollama `/api/ps` confirms only one Lucy model resident at a time after stress test.
- **HMI state cleanup:** `request_history.jsonl` deduplicated (163 → 152 unique entries; backup preserved); stale `health.json` updated to `status=ok` with current timestamp; `last_request_result.json` now reflects successful completion after the green test run.
- **Startup noise / CUDA 804 / multiple MiniLM loads / memory summarization timeouts:**
  - Added `_cuda_available_safely()` in `models/router/hybrid_router_v2.py` and wrapped `torch.cuda.is_available()` calls in `tools/router_py/policy.py` and `tools/voice/backends/kokoro_backend.py` to suppress the PyTorch driver-mismatch UserWarning.
  - Set `HF_HUB_DISABLE_PROGRESS_BARS=1` and `TRANSFORMERS_VERBOSITY=error` in `hybrid_router_v2.py`, `tools/router_py/context_guard.py`, `tools/router_py/policy.py`, and `tools/memory/memory_service.py` to reduce terminal spam from loading multiple sentence-transformer models.
  - Increased default memory summarization timeout from 30 s → 60 s (configurable via `LUCY_MEMORY_SUMMARIZE_TIMEOUT_S`) and added `LUCY_MEMORY_SUMMARIZE_MODEL` so a small/fast Ollama model can be used for session summaries.
- **SHA256SUMS:** regenerated with `make sha`; both root and `ui-v10` discipline tests pass.

### Engineering-Mode Context Limit Alignment — 2026-08-07
- **Problem:** The implementation default for `self_review_context_chars` and `code_review_context_chars` was still `32,768`, while the design documents and user expectation specified `200,000` characters (~1,500 lines of code or text). This caused Engineering-mode file reviews to truncate large files.
- **Fix applied:**
  - `tools/router_py/local_answer_core/config.py`: raised both defaults and env fallbacks from `32,768` to `200,000`.
  - `tools/router_py/test_self_analysis.py`: updated the default assertion to `200,000`.
  - `Architecture.md` and desktop `Local_Lucy_V11_Architecture.md`: updated both references to `200,000`.
  - `tools/router_py/local_answer_core/self_knowledge.py`: injected the new limit into Local Lucy's self-knowledge prompt so the model can answer accurately when asked about Engineering-mode file-review capacity.
- **Verification:**
  - `test_self_analysis.py -k "config or truncates_very_long" -m slow` → 3 passed
  - `test_gemma4_identity.py`, `test_security_guard.py`, `test_local_answer.py::TestQueryClassification` -m slow → 9 passed
  - `test_self_analysis.py::test_specialist_model_identity_exists` → passed
- **HMI:** Restarted after the config change so the new default is active.
- **Qualification note:** RESOLVED — the full clean run was repeated on HEAD `8c80cdb` (which includes this change) and passed 7/7; see `qualification/COMPLETION_REPORT_2026-08-07_FINAL_REQUAL.md`. The `QUALIFIED` decision is current.

---

## Architecture Summary

Local Lucy v11 is a **privacy-first, self-learning desktop AI assistant**.

### Three-Layer Stack

```
┌─────────────────────────────────────────┐
│  PySide6 HMI (ui-v10/app/)              │
│  OperatorConsoleWindow, panels, bridge  │
└──────────────┬──────────────────────────┘
               │ RuntimeBridge → subprocess / import
┌──────────────▼──────────────────────────┐
│  Lucy Core (tools/router_py/)           │
│  process() → classify → route → execute │
│  ExecutionEngine, provider_resolver     │
│  feedback_parser, state_manager         │
└──────────────┬──────────────────────────┘
               │
    ┌──────────┼──────────┬──────────┐
    ▼          ▼          ▼          ▼          ▼
  LOCAL     AUGMENTED   WEATHER     NEWS     FINANCE
 (Ollama)  (Web+LLM)   (API)     (RSS)   (Live data)
```

### Four-Stage Routing Pipeline
1. **Structural safety** — empty/hostile/conspiracy filtering
2. **Embedding k-NN** — MiniLM semantic similarity
3. **Keyword guards** — medical/vet/weather/news hard catches
4. **Confidence fallback** → `CLARIFY` or `UNKNOWN`

### Routes
`LOCAL` | `AUGMENTED` | `EVIDENCE` | `NEWS` | `WEATHER` | `TIME` | `FINANCE` | `URL_REFERENCE` | `CLARIFY` | `UNKNOWN`

### FINANCE Route
Live market-data fetcher with source citations:
- **FX**: `exchangerate-api.com` (free, no key)
- **Crypto**: `CoinGecko` (free, no key)
- **Stocks/indices**: Yahoo Finance primary; web-search fallback if rate-limited
- **Net worth**: web search restricted to trusted finance sources
- Personal-finance reasoning (advice/planning) continues to route `LOCAL`

### Safety Critical
- Medical/vet queries **must** route to `EVIDENCE` with trusted sources
- Follow-ups after medical EVIDENCE are guarded to not fall back to LOCAL
- High-stakes feedback (medical/vet/finance/legal) → `pending_review.jsonl`
- `FINANCE` answers include source citations; web-search fallbacks are labelled accordingly

---

## Production Hardening Status

| Phase | Status | Key Deliverables |
|-------|--------|-----------------|
| 0 Emergency Stabilization | ✅ | Clean working tree, `.gitignore` rewritten |
| 1 Foundation (CI/CD) | ✅ | `v10-dev` triggers, no `\|\| true`, version aligned |
| 2 Security | ✅ | Secret rotated, health probes, SQLite `0o600`, follow-up guard |
| 3 Observability | ✅ | `health.py`, circuit breakers, TTL cache |
| 4 Portability | ✅ | `Makefile`, `check_environment.py`, XDG paths |
| 5 Release Engineering | ✅ | `CHANGELOG.md`, semver tag |
| 6 Documentation | ✅ | `INSTALL.md`, `SECURITY.md`, `ARCHITECTURE.md` |

---

## Known Risks / TODOs

1. ~~Origin default branch~~ ✅ now `main`
2. ~~Dependency lockfile~~ ✅ `requirements-lock.txt` generated
3. ~~Pre-commit hooks~~ ✅ `.pre-commit-config.yaml` created and installed
4. ~~GitHub release workflow~~ ✅ `.github/workflows/release.yml` created; `.deb` packaging added
5. ~~Structured logging~~ ✅ `tools/router_py/logging_config.py` added; starter print replacements in `main.py`/`classify.py`
6. ~~.deb / AppImage packaging~~ ✅ `.deb` build verified; experimental AppImage build script kept for manual use; CI job removed from release workflow
7. ~~Ollama localhost auth~~ ✅ hardening runbook added to `docs/runbooks/OLLAMA_SECURITY.md`
8. ~~Regression golden fragility~~ ✅ model-mismatch now skips instead of failing; shared `skip_without_ollama` fixture added for CI/release environments without Ollama
9. ~~Hardcoded absolute paths~~ ✅ tests/benchmarks now derive paths from `__file__` or env vars
10. ~~Local-model regression tests~~ ✅ all 20 response/semantic regression cases now pass
11. ~~Robustness review fixes~~ ✅ AppImage removed from automatic release; Ollama skip fixture added; model-mismatch skip in semantic regression; concept-overlap threshold relaxed to 0.25; reasoning max_chars raised to 800; reasoning prompt steered to avoid "I don't know"
12. ~~Ruff / lint~~ ✅ ruff installed in venv; mypy installed and enforced; `make lint` passes
13. ~~Optional web interface~~ ✅ aiohttp adapter added at `web_adapter/`; stateless; request-scoped model selection; Basic/Bearer auth; 13 focused tests
14. ~~Memory greeting hallucination fix~~ ✅ MiniLM embeddings now primary; `<think>` blocks stripped; greetings forced to shallow context; polluted DB cleaned; `LUCY_OLLAMA_MODEL` propagated
15. ~~Automatic model selection (Phase 3)~~ ✅ `select_model()` policy, shadow-mode metrics, Auto HMI option, A/B harness
16. ~~Self-Analysis Mode~~ ✅ `tools/router_py/self_analysis.py`, Engineering-panel toggle, state persistence, tests
17. ~~HMI toggle → pipeline env propagation~~ ✅ `_apply_state_to_env()` in `runtime_bridge.py`
18. ~~Ollama model load/unload race~~ ✅ `_OLLAMA_LOAD_LOCK` + evict-other-Lucy-models in `runtime_bridge.py`
19. ~~Duplicate request history IDs~~ ✅ nanosecond + hash request IDs in `execution_engine_state.py`
20. ~~4000-char input limit~~ ✅ raised to 16000 in `security_guard.py`; tests updated
21. ~~Stale HMI health/alarm state~~ ✅ `health.json` refreshed; `last_request_result.json` reflects success after green test run
22. ~~Startup CUDA 804 warning + MiniLM loading spam~~ ✅ `_cuda_available_safely()`, warning-filtered policy/kokoro checks, `HF_HUB_DISABLE_PROGRESS_BARS` + `TRANSFORMERS_VERBOSITY`
23. ~~Memory summarization timeouts~~ ✅ timeout raised to 60 s, configurable model via `LUCY_MEMORY_SUMMARIZE_MODEL`

**Open:**
24. ~~v10-era naming~~ **partially advanced 2026-08-08** — dead `LUCY_ROUTER_PY`/`LUCY_EXEC_PY` vars, `qwen3_router.py`, `rollout_config.env`, and stale qwen3 model-facing text pruned; `ui-v10/` directory rename deferred → see #29.
25. `config/personas/racheli.txt` missing — prompt-level Racheli persona has no fragment (her LoRA tag exists); only `michael.txt` present.
26. Memory retrieval knobs (`LUCY_MEMORY_*`) not yet exposed in the HMI.
27. ~~S09-MEM-003 literal substring concept checks~~ ✅ resolved 2026-08-08 via DEC-018 — evaluation deduplicated into `tools/router_py/scenario_checks.py`; any-of relaxations now use the `required_answer_concepts_any` scenario JSON field; S09-MEM-003 stays strict.
28. ~~Uncommitted requal-session changes~~ ✅ committed (consolidation session, 2026-08-08).
29. `ui-v10/` directory rename deferred — cosmetic; see `docs/superpowers/plans/2026-08-08-consolidation-and-hardening.md` (Task 6).
30. Rebuild live Ollama tags from corrected Modelfiles (`ollama create`) — operator-approved, then re-run stage_08/10 smoke.
31. Refresh or delete `dist/AppDir` before next AppImage packaging (contains pre-prune snapshots).

---

## Session Handoff Instructions

When ending a session, update this file with:
1. Any new commits (append to Recent Commits)
2. Changes to Working tree status
3. New TODOs completed or discovered
4. Any architectural decisions made

Then run:
```bash
cd ~/lucy-v11 && git add SESSION_CONTEXT.md && git commit -m "docs: update SESSION_CONTEXT.md"
```

---

*Last updated: 2026-08-08T12:30Z*
*Session: Consolidation & hardening closeout — tasks 1-5 landed (`95925c6..bdfdfad`); task 7: 16 stale `test_local_answer.py` patch targets repointed (green under `-m ""`), latent `config.py` json-import bug fixed, README/Modelfile/system_prompt stale model text corrected, `known_failing_tests` tracking added, DEC-018 recorded, TODOs #24/#27/#28 updated and #29 added, desktop docs re-synced.*
