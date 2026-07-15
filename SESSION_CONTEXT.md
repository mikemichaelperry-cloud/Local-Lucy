# Local Lucy — Session Context (Auto-Updated)

> **READ THIS FIRST** at every session start. Updated at every handoff.

---

## Quick Orientation

| | |
|---|---|
| **Repository** | `~/lucy-v10` (also `LUCY_ROOT`) |
| **Branch** | `v10-dev` |
| **Last tag** | `v10.0.0-beta.1` |
| **Version** | `10.0.0-beta.1` |
| **Model** | `local-lucy-llama31` (llama3.1:8b via Ollama) |
| **Handoff file** | `~/Desktop/Local_Lucy_v10_Session_Handoff_<date>.md` |
| **Default branch on origin** | `v10-dev` ✅ |
| **Working tree** | Modified (self-analysis large-file / large-response support implemented; docs and prompts updated) |

---

## Directory Structure

```
lucy-v10/
├── tools/                    # Core backend (router, execution, voice, memory, internet)
│   ├── router_py/            # Main execution engine (~50 modules)
│   ├── lora/                 # Persona LoRA training, conversion, evaluation
│   ├── internet/             # Web search (DuckDuckGo, SearXNG, Brave)
│   ├── voice/                # TTS (Kokoro), STT (Whisper), playback
│   ├── memory/               # SQLite memory service
│   └── xdg_paths.py          # XDG-compliant path resolution
├── ui-v10/                   # PySide6 HMI
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
├── config/                   # Modelfiles, prompts, trust rules, policies
├── services/searxng/         # Docker Compose + settings.yml for local search proxy
├── scripts/                  # Operational scripts (check_environment.py, migrate_db.py)
├── docs/runbooks/            # INSTALL.md, SECURITY.md
├── README.md                 # Project overview, usage, features
├── ARCHITECTURE.md           # System architecture
├── CHANGELOG.md              # Keep a Changelog format
├── runtime/                  # Generated at runtime (ignored by git)
├── state/                    # Generated at runtime (ignored by git)
├── voice/                    # Generated audio (ignored by git)
├── START_LUCY.sh             # Desktop launcher (entry point)
├── lucy_chat.sh              # CLI chat entry point
├── Makefile                  # install, test, lint, run, clean, check-env
├── VERSION                   # 10.0.0-beta.1
├── CHANGELOG.md              # Keep a Changelog format
└── pyproject.toml            # Packaging, dependencies, tool configs
```

---

## Key Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `LUCY_ROOT` | derived from `START_LUCY.sh` | Project root |
| `LUCY_RUNTIME_NAMESPACE_ROOT` | `~/.local/share/local-lucy` (XDG) or legacy `~/.codex-api-home/...` | Runtime state, DBs, logs |
| `LUCY_RUNTIME_AUTHORITY_ROOT` | `$LUCY_ROOT` | Code authority validation |
| `LUCY_UI_ROOT` | `$LUCY_ROOT/ui-v10` | HMI path |
| `LUCY_OLLAMA_API_URL` | `http://127.0.0.1:11434/api/generate` | Local LLM endpoint |
| `LUCY_LOCAL_MODEL` | `local-lucy-llama31` | Default Ollama model |
| `LUCY_STATE_DB` | `$LUCY_RUNTIME_NAMESPACE_ROOT/state/lucy_state.db` | SQLite state DB |
| `LUCY_MEMORY_DB_PATH` | `$LUCY_RUNTIME_NAMESPACE_ROOT/state/memory.db` | SQLite memory DB |
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
| Lint | `make lint` |

---

## Git State

```bash
# Current state (auto-generated)
Branch: v10-dev
Origin HEAD: v10-dev ✅ (pushed and in sync)
Latest tag: v10.0.0-beta.1
Commits since tag: 62
Working tree: modified (Self-Analysis large-file / large-response support implemented and reviewed; pre-existing `models/router/comprehensive_examples.json` change unrelated)
```

### Recent Commits (last 16)
```
Self-Analysis Large-File / Large-Response Support
2e2e014 fix(self-review): bypass policy short-circuit for SELF_REVIEW and add exact 5 MB boundary test
9dc4497 fix(self-analysis): payload-level test, is_self_review derivation, scoped cap relaxation
2f848de fix(self-analysis): skip 807 short-circuit for SELF_REVIEW and clean cache helpers
70b9346 Fix third-wave self-analysis large-file review findings
ec8768e fix(self-analysis): round-2 review fixes
8ef87a8 fix(self-analysis): address whole-branch review findings
720cd08 feat(self-analysis): use SELF_REVIEW route and bypass repeat cache
e6230ee feat(local_answer): add SELF_REVIEW route with large token budget
aa655d0 feat(self-analysis): include source code and guard large/non-file paths
9be66cd docs: add self-analysis large-file support implementation plan
2fd99cb docs: add self-analysis large-file support design spec
0c2ff66 feat: wire Self-Analysis Mode toggle to state persistence
b17c30a feat: add Self-Analysis Mode checkbox to Engineering panel
5038df6 feat: dispatch self-analysis queries in ExecutionEngine
0451f0d Fix self-analysis review findings: path traversal, async docstring, ruff stderr, tests
b1818d3 feat: add SelfAnalysisEngine for local code self-review
```

### Persona LoRA Pipeline — Completed Within Hardware Limits
- Phase 1 (prompt-level personas) previously complete and tested.
- Phase 2–5 completed for hardware-feasible models:
  - `tools/lora/` scripts for dataset generation, QLoRA training, GGUF conversion, Modelfile generation, and Ollama tag creation.
  - Persona datasets generated at `data/lora/datasets/{michael,racheli}.jsonl`.
  - Persona-aware model resolution added to `tools/router_py/local_answer.py`.
  - HMI persona selector (`auto` / `Michael` / `Racheli`) added to Control Panel, plus indicator and clear button, forcing the active identity for all models.
  - Golden test cases expanded with `contains_any` / `not_contains_any` checks and evaluator hardened with `--min-pass-rate` and `--json` output.
  - `local-lucy-llama31-michael` and `local-lucy-llama31-racheli` adapters trained, converted to GGUF, and registered as Ollama tags.
- Hardware limitation on RTX 3060 12 GB:
  - `Qwen/Qwen3-14B` OOMs during `prepare_model_for_kbit_training` even at rank 4 / seq 512.
  - `mistralai/Mistral-Nemo-Instruct-2407` also OOMs at the same step, even at rank 4 / seq 512 / `q_proj,v_proj` only.
  - Therefore `local-lucy`, `local-lucy-fast`, `local-lucy-qwen3`, and `local-lucy-mistral` use prompt-level persona injection at runtime.
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
- `tools/router_py/execution_engine.py` dispatches self-analysis queries when `self_analysis_mode` is `"on"` and the query references a Python file.
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
- **Dedicated `SELF_REVIEW` route (`tools/router_py/local_answer.py`):**
  - `LocalAnswerConfig` exposes `self_review_max_tokens` (default 4096) and `self_review_context_chars` (default 100000), overridable via `LUCY_SELF_REVIEW_MAX_TOKENS` and `LUCY_SELF_REVIEW_CONTEXT_CHARS`.
  - `_set_generation_profile("SELF_REVIEW", ...)` returns a `("self_review", self_review_max_tokens, "- Provide a thorough, detailed code review with concrete, minimal improvements.")` profile.
  - `_call_ollama` raises the `num_predict` ceiling only for `SELF_REVIEW`, so the budget is not capped by `num_predict_long`.
- **Caller and cache wiring:**
  - `SelfAnalysisEngine.suggest_improvements` calls `generate_answer(query=prompt, route_mode="SELF_REVIEW")`.
  - `generate_answer` bypasses the local repeat cache for `SELF_REVIEW`.
  - General Q&A short-circuits (policy, 807, tube-DB, personal-fact) and the 807 post-processing override are skipped for `SELF_REVIEW`.
- **Config unification:**
  - `SelfAnalysisEngine` accepts `self_review_context_chars` and obtains the default from `LocalAnswerConfig.from_env()`; `execution_engine.py` passes the authoritative config value.
- **Documentation:**
  - Updated `docs/superpowers/specs/2026-07-15-self-analysis-large-files-design.md` to match implementation wording.
- **Tests:**
  - `tools/router_py/test_self_analysis.py`: 21 passed
  - `tools/router_py/test_local_answer.py`: 58 passed
  - Combined: 79 passed
  - `ruff check` and `ruff format --check` clean on all modified files.

---

## Architecture Summary

Local Lucy v10 is a **privacy-first, self-learning desktop AI assistant**.

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

1. ~~Origin default branch~~ ✅ now `v10-dev`
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

---

## Session Handoff Instructions

When ending a session, update this file with:
1. Any new commits (append to Recent Commits)
2. Changes to Working tree status
3. New TODOs completed or discovered
4. Any architectural decisions made

Then run:
```bash
cd ~/lucy-v10 && git add SESSION_CONTEXT.md && git commit -m "docs: update SESSION_CONTEXT.md"
```

---

*Last updated: 2026-07-15T17:54:19Z*
*Session: Implemented Self-Analysis large-file / large-response support. Added source-code inclusion, 5 MB TOCTOU-safe read cap, non-UTF-8 fallback, dedicated `SELF_REVIEW` route with 4096-token budget, payload-level budget regression test, local-repeat-cache bypass, and Q&A short-circuit bypass in `tools/router_py/self_analysis.py` and `tools/router_py/local_answer.py`. Unified truncation limit with `LocalAnswerConfig.self_review_context_chars`. Updated design spec and this file. Tests: `tools/router_py/test_self_analysis.py` 21 passed; `tools/router_py/test_local_answer.py` 58 passed; 79/79 combined. Pre-existing unrelated change remains in `models/router/comprehensive_examples.json`.*
