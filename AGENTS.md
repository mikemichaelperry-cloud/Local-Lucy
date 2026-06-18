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
