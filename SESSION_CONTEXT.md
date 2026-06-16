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
| **Default branch on origin** | `v9-dev` ⚠️ needs GitHub admin fix |
| **Working tree** | Clean |

---

## Directory Structure

```
lucy-v10/
├── tools/                    # Core backend (router, execution, voice, memory, internet)
│   ├── router_py/            # Main execution engine (~50 modules)
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
├── models/router/            # Embedding router, training data, background learner
├── config/                   # Modelfiles, prompts, trust rules, policies
├── services/searxng/         # Docker Compose + settings.yml for local search proxy
├── scripts/                  # Operational scripts (check_environment.py, migrate_db.py)
├── docs/runbooks/            # INSTALL.md, SECURITY.md
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
| Pytest (full) | `make test` |
| Lint | `make lint` |

---

## Git State

```bash
# Current state (auto-generated)
Branch: v10-dev
Origin HEAD: v10-dev ✅ (pushed and in sync)
Latest tag: v10.0.0-beta.1
Commits since tag: 30
Working tree: clean
```

### Recent Commits (last 13)
```
79136ec docs: update README for v10 — llama3.1 default, FINANCE route, XDG paths, packaging
63bd4a2 docs: update SESSION_CONTEXT.md — origin/v10-dev is in sync
09965c5 docs: update SESSION_CONTEXT.md — GitHub default branch is v10-dev
e3fe120 ci: add experimental AppImage packaging
f6ffe1a test: update default model expectation to local-lucy-llama31
332c097 docs: update SESSION_CONTEXT.md
8e6c152 fix(local): steer first-person and reasoning prompts; re-record semantic golden responses
b480477 chore: ignore pre-existing F841 issues in local_answer.py
f2efa6d ci: add release workflow and Debian packaging
53b2882 refactor(tests): remove hardcoded absolute paths and use env-driven runtime root
9aa193e feat(logging): add logging_config wrapper and replace print statements
eee7ee6 chore: add ruff config with per-file ignores for legacy code
97af56e chore: ignore egg-info build artifacts
```

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
6. ~~.deb / AppImage packaging~~ ✅ `.deb` build verified; experimental AppImage build script + CI job added
7. ~~Ollama localhost auth~~ ✅ hardening runbook added to `docs/runbooks/OLLAMA_SECURITY.md`
8. ~~Hardcoded absolute paths~~ ✅ tests/benchmarks now derive paths from `__file__` or env vars
9. ~~Local-model regression tests~~ ✅ all 20 response/semantic regression cases now pass

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

*Last updated: 2026-06-16T15:55:00Z*
*Session: README refreshed for v10 current state and pushed to origin/v10-dev*
