# Local Lucy v9 — Codex Execution Rules

## Authority

- The authoritative working root is:
  /home/mike/lucy-v9
- Snapshot sync target:
  /home/mike/lucy-v9/snapshots/opt-experimental-v9-dev (mirror, not source)

- Do not modify:
  - launcher structure
  - HMI structure
  - unrelated subsystems

- Backend is authoritative. UI must not fabricate state.

## System Privileges

- **Never use `sudo`.** The system blocks external sudo requests and the shell crashes.
- Make changes only within `~/lucy-v9/` directories.
- **V8 is frozen.** Do not modify `/home/mike/lucy-v8/` under any circumstances.
- V9 (`/home/mike/lucy-v9/`) is the sole active development branch.
- For system-level changes (e.g., systemd, global env vars), use user-level alternatives:
  - Modify `START_LUCY.sh` to export env vars
  - Use per-user systemd overrides (`~/.config/systemd/user/`) if available
  - Never edit `/etc/systemd/system/` or other root-owned paths

## Operating Principles

- No optimistic behavior
- No silent side effects
- No hallucinated files
- Test every change
- Prefer Python over shell for logic
- Prefer `StrReplaceFile` over `WriteFile` for edits
- Sync all backend changes to `snapshots/opt-experimental-v9-dev/`

## Feedback Learning System (Conversational)

Local Lucy can learn from natural-language user feedback without CLI commands.

### How it works

When you react to a response, Lucy detects the feedback *before* routing it as a new query:

| You say | Detected as | Action |
|---|---|---|
| "that was wrong, it should have been LOCAL" | Route correction | Logs `{query, correct_route: LOCAL}` → rebuilds embeddings |
| "wrong route, that was NEWS" | Route correction | Same, with route=NEWS |
| "that was a bad answer" | Negative quality | Logs complaint (no auto-route guess) |
| "perfect, thank you" | Positive quality | Confirms/strengthens existing route |
| "forget that" | Retraction | Removes prior exchange from memory |

### Files

- `tools/router_py/feedback_buffer.py` — Ring buffer of last 5 exchanges (persisted to runtime namespace)
- `tools/router_py/feedback_parser.py` — Pattern-based NL feedback detection + logging
- `models/router/user_feedback.jsonl` — Logged corrections (ingested by background_learner.py)
- `models/router/background_learner.py` — Rebuilds embedding index from feedback + auto-feedback

### Attribution

Feedback is always attributed to the **most recent exchange** in the buffer. The buffer records:
- Query text
- Route chosen
- Intent family
- Response text (truncated)
- Confidence

### Learning trigger

After each logged correction, `maybe_auto_learn(min_entries=1)` is called. This starts a background thread that:
1. Reads `user_feedback.jsonl`
2. Deduplicates by query
3. Rebuilds `comprehensive_embeddings.npy` and `comprehensive_examples.json`
4. The next query uses the updated index immediately

### Adding new feedback patterns

Edit `feedback_parser.py`:
- `ROUTE_CORRECTION_PATTERNS` — regexes that extract route names
- `ANSWER_NEGATIVE_PATTERNS` — negative quality signals
- `ANSWER_POSITIVE_PATTERNS` — positive quality signals
- `RETRACTION_PATTERNS` — commands to forget/retract

Patterns are checked in order: route correction → retraction → negative → positive.

### Architecture Refactor Status

Stages 0–9 complete. Python-native path is authoritative. Shell/parity paths removed.
See `tools/router_py/ARCHITECTURE.md` for full pipeline diagram.

New modules introduced:
- `tools/router_py/request_pipeline.py` — pipeline choke point
- `tools/router_py/request_types.py` — centralized dataclasses
- `tools/router_py/provider_resolver.py` — single source of truth for provider selection
- `tools/router_py/response_formatter.py` — pure formatting/validation utilities

All entry points (CLI, HMI, voice) now call `main.run()`.

### Testing

```bash
cd ~/lucy-v9/ui-v9
.venv/bin/python3 -m pytest tests/ -q
```

Also run the fast routing stress test:
```bash
.venv/bin/python3 fast_routing_stress_test.py
```

Router tests:
```bash
cd ~/lucy-v9
source ui-v9/.venv/bin/activate
python -m pytest tools/router_py/ --ignore=tools/router_py/test_resource_leaks.py -q
```

### Sync rule

Any change to `tools/router_py/` or `models/router/` must be copied to:
```
snapshots/opt-experimental-v9-dev/tools/router_py/
snapshots/opt-experimental-v9-dev/models/router/
```

---

## 🎯 NEXT SESSION BOOTSTRAP — Production Migration (Streams 1–6 Complete)

**Date written:** 2026-05-14  
**Final commit:** `dd9024a8` (pushed to `origin/main`)  
**System state:** `main` is up to date with `origin/main`. Clean working tree.  
**Active router:** Python-native (`LUCY_ROUTER_PY=1`, `LUCY_EXEC_PY=1`)  
**Model:** ModernBERT hybrid + keyword guards, 645 examples  
**GPU constraint:** LOW VRAM. No GPU tests. No model loading in tests.  

---

### What "Production Ready" Means Here

The user's rating for this session:
- Architecture: 8.8/10
- Operational coherence: 8.5/10
- Report reliability: 7.5/10
- Ready for daily dogfood: **yes**
- Ready for no-supervision production: **not yet**

V8 is frozen at tag `local-lucy-v8-freeze-2026-05-17`. Do not modify V8.
V9 is the active development branch. v10 is the target beta release.
All work, fixes, and improvements belong in V9 only. No cross-contamination to V8.

---

### ✅ What Is Working Now (Do Not Break)

1. **State pipeline is coherent**
   - Python router → `PipelineContext` → `ExecutionEngine` → `StateWriter`
   - JSON files (`last_request_result.json`, `last_route.json`, `request_history.jsonl`) are the HMI-facing contract
   - SQLite (`lucy_state.db`) is the durable internal state
   - `.env` writes are deprecated (commented out, not deleted)

2. **request_id is unified end-to-end**
   - `main.py` generates `sha256(question)[:16]`
   - Flows through `PipelineContext.extras` → `ExecutionEngine` → `StateWriter`
   - Present in JSON payload, SQLite metadata, and history entries
   - Test: `test_request_id_propagation()`

3. **Training data is git-stable**
   - `comprehensive_examples.json` no longer drifts with runtime timestamps
   - Timestamps normalized to `"training_data"`
   - Mutable metadata goes to untracked `examples_metadata.json`

4. **Shared payload builders exist**
   - `tools/router_py/payload_builders.py` — pure functions used by both shell and Python routers
   - `build_route_snapshot_payload()`, `determine_route_source_type()`, `build_history_entry()`

5. **HMI displays real state**
   - 138/138 inspection checks pass
   - 9/9 non-GPU offscreen tests pass
   - Dead preprocess fields removed from display

---

### 🔧 Known Issues (Next Priority Order)

**Priority 1 — Watch during daily use (no code changes yet):**
- Does HMI always show the current route correctly?
- Does `request_history.jsonl` grow sensibly?
- Does SQLite metadata match JSON `request_id`?
- Does `comprehensive_examples.json` stay clean?
- Does `git status` remain clean after normal usage?
- Does weather/time/local routing behave consistently?

**Priority 2 — Safe cleanup (after 1–2 weeks stable JSON-only operation):**
- Delete `_write_state_to_files()`, `get_state_file_paths()`, and `.env` read-back helpers from `execution_engine_state.py`
- Search for `TODO: Remove` comments
- This is low risk — the methods are already dead code

**Priority 3 — Fix when VRAM is available or mocks are written:**
- `test_voice_ptt_offscreen.py` — segfault (whisper.cpp server processes occupy VRAM)
- `test_whisper_gpu_cpu_fallback_offscreen.py` — GPU model loading fails
- `test_whisper_gpu_success_offscreen.py` — GPU model loading fails

**Priority 4 — Orphaned file (cosmetic):**
- `last_preprocess.json` — no writer exists in Python router
- Fields already removed from HMI, so this is harmless
- Can add a no-op writer for completeness, or ignore

---

### 🚧 Architecture Boundaries (Do Not Cross Without Approval)

| Area | Rule |
|------|------|
| Router classification | Do not change ModernBERT or keyword guard behavior |
| SQLite schema | Do not modify `lucy_state.db` or `memory.db` schema |
| HMI redesign | Forbidden per user constraint set |
| Model weights | Do not retrain or replace embedding index without explicit instruction |
| Launcher structure | Do not modify `START_LUCY.sh` structure |
| Voice runtime | Do not modify whisper.cpp or kokoro integration |

**Allowed changes:**
- `execution_engine_state.py` — state persistence
- `execution_engine.py` — dispatch and state write calls
- `payload_builders.py` — pure payload formatting
- Tests in `tools/router_py/test_*.py` and `ui-v9/tests/test_*.py`
- Documentation and reports

---

### 📁 Load-Bearing Files

| File | What it does | Touch with care |
|------|-------------|-----------------|
| `tools/router_py/main.py` | Entry point, generates `request_id` | Yes — keep request_id contract |
| `tools/router_py/request_pipeline.py` | Pipeline choke point, builds `PipelineContext` | Yes — frozen dataclass contract |
| `tools/router_py/execution_engine.py` | Dispatches routes, calls state writes | Yes — all 6 paths must call JSON writes |
| `tools/router_py/execution_engine_state.py` | `StateWriter` — JSON + SQLite persistence | Yes — public API must not break |
| `tools/router_py/payload_builders.py` | Shared pure payload builders | Yes — both routers depend on this |
| `tools/router_py/request_types.py` | Centralized frozen dataclasses | Yes — schema changes ripple |
| `tools/runtime_request.py` | Shell router, imports payload builders | Yes — graceful fallback required |
| `ui-v9/app/services/state_store.py` | HMI reads JSON state files | No — read-only per constraints |
| `ui-v9/app/panels/status_panel.py` | HMI displays state | No — read-only per constraints |
| `models/router/background_learner.py` | Rebuilds embedding index | Yes — keep timestamp normalization |

---

### 🧪 Test Commands (Copy-Paste Ready)

```bash
# Full router suite (CPU only, ~1min40s)
cd ~/lucy-v9
source ui-v9/.venv/bin/activate
python -m pytest tools/router_py/ -q

# StateWriter specifically
python -m pytest tools/router_py/test_execution_engine_state.py -q

# E2E voice (mocked, no GPU)
python -m pytest tools/router_py/test_e2e_hmi_voice.py -q

# HMI comprehensive inspection (offscreen Qt)
QT_QPA_PLATFORM=offscreen python3 ui-v9/tests/test_comprehensive_hmi_inspection.py

# HMI offscreen tests (non-GPU only)
for f in ui-v9/tests/*offscreen*.py; do
  QT_QPA_PLATFORM=offscreen timeout 30 python3 "$f" && echo "PASS $f" || echo "FAIL $f"
done

# Live end-to-end (single request)
LUCY_ROUTER_PY=1 LUCY_EXEC_PY=1 LUCY_AUGMENTATION_POLICY=fallback_only \
  python3 -c "import sys; sys.path.insert(0,'tools'); from router_py.main import execute_plan_python; \
  r = execute_plan_python('What is 2+2?', policy='fallback_only', timeout=30); \
  print(r.status, r.route, r.request_id)"
```

---

### 📊 State File Locations

**Unified location (canonical):**
```
~/.codex-api-home/lucy/runtime-v9/state/
├── current_state.json          # HMI control state (unified — see below)
├── last_request_result.json    # Full request payload (NEW — Stream 2)
├── last_route.json             # Route snapshot (NEW — Stream 2)
├── request_history.jsonl       # Deduplicated history (NEW — Stream 2)
├── runtime_lifecycle.json      # Process status
├── health.json                 # System health
├── voice_runtime.json          # Voice backend status

~/.codex-api-home/lucy/runtime-v9/
├── lucy_state.db               # SQLite routes/outcomes
└── memory.db                   # SQLite memory
```

**Legacy location (project root):**
```
/home/mike/lucy-v9/state/
├── current_state.json          # Legacy fallback
```

**Why two locations?** The project was created with state in the repo directory, but the HMI and `runtime_control.py` default to `~/.codex-api-home/lucy/runtime-v9/`. Before 2026-05-16, `START_LUCY.sh` and the HMI read/wrote different `current_state.json` files, causing silent drift (e.g. model mismatch warnings on startup).

**Fix applied (2026-05-16):**
- `START_LUCY.sh` now exports `LUCY_RUNTIME_STATE_FILE=~/.codex-api-home/lucy/runtime-v9/state/current_state.json`
- `router_py/main.py` `load_state_from_file()` checks `LUCY_RUNTIME_STATE_FILE` env var first
- This ensures all entry points (launcher, HMI, runtime_control.py, main.py) use the SAME `current_state.json`

**Note:** `~/.codex-api-home` is a legacy directory name from the Codex era. It contains only Local Lucy data. Renaming it is deferred to a later cleanup sprint.

---

### 📝 Report Locations

| Report | Path |
|--------|------|
| Full migration report | `reports/Production_Migration_Report_Streams_1-6_2026-05-14.md` |
| Session handoff | `dev_notes/SESSION_HANDOFF_2026-05-14T19-35-00+0300.md` |
| Desktop handoff | `~/Desktop/SESSION_HANDOFF_2026-05-14T19-35-00+0300.md` |
| Desktop report | `~/Desktop/Production_Migration_Report_Streams_1-6_2026-05-14.md` |
| Approved plan | `.kimi/plans/captain-marvel-ice-static.md` |

---

### 🔑 Key Environment Variables

```bash
LUCY_ROUTER_PY=1          # Use Python router (active)
LUCY_EXEC_PY=1            # Use Python execution engine (active)
LUCY_AUGMENTATION_POLICY=fallback_only   # Current policy
LUCY_UI_STATE_DIR=~/.codex-api-home/lucy/runtime-v9/state  # JSON state output
LUCY_STATE_DB=~/lucy-v9/state/lucy_state.db  # SQLite DB path
```

---

### ⚠️ Things That Have Confused Me Before

1. **`request_id` in `PipelineContext`**: `PipelineContext` is a frozen dataclass. Unknown keys from `context` dict are merged into `.extras` via `dataclasses.replace()`. `to_dict()` propagates `.extras` flat. This is the correct contract.

2. **SQLite namespaces**: `StateManager` uses hostname-based namespaces by default (`mike-System-Product-Name_<pid>_<timestamp>_<hash>`), not `"default"`. The `default` namespace exists but is empty in normal operation. Tests create their own namespaces.

3. **`comprehensive_examples.json` learner drift**: Route label changes (e.g. `LOCAL` → `WEATHER` from feedback) are **expected** and correct. Only timestamp drift was a bug. Do not revert route label changes unless the user explicitly asks.

4. **`.env` deprecation vs. deletion**: The `.env` write methods are commented out in the public entry point but the methods still exist. This is intentional — they will be fully removed after burn-in.

5. **HMI offscreen tests are NOT pytest tests**: They are standalone Python scripts with `main()` functions. Run them directly, not via `pytest`.

6. **No GPU in tests**: The user has low VRAM (~3.7GB used by whisper-server processes). Never run tests that load torch/transformers models. All router tests use mocks.

7. **Two `current_state.json` files**: Before 2026-05-16 there were two independent files:
   - `~/.codex-api-home/lucy/runtime-v9/state/current_state.json` — HMI default, runtime_control.py default
   - `/home/mike/lucy-v9/state/current_state.json` — START_LUCY.sh, main.py legacy path
   
   They could diverge silently (e.g. model mismatch warnings). Fixed by adding `LUCY_RUNTIME_STATE_FILE` env var to START_LUCY.sh and making main.py respect it. Always use the env var when referring to current_state.json.

---

### 🛡️ Operational Guardrails

1. **Set `LUCY_AUTO_LEARN=0` during development, audit, or test sessions** unless the explicit task is to test learner behavior. Do not allow test prompts or agent-generated corrections to mutate production router examples.

2. **Sync only after tests pass.** Never push a dirty snapshot.

3. **Do not use `rsync --delete` unless explicitly approved by Michael.** Destructive syncs can wipe snapshot files.

4. **Snapshot is NOT authoritative.** Python-native path is authoritative. Shell/parity paths are legacy compatibility only and must not be expanded.

5. **Stop and ask Michael before editing:**
   - SQLite schema changes
   - Router classification changes
   - HMI redesign
   - Model replacement or retraining
   - Launcher restructuring
   - Production memory changes

---

*End of bootstrap. Read this at the start of every new session before touching code.*
