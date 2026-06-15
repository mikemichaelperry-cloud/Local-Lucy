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
Origin HEAD: v9-dev  ⚠️  (needs GitHub admin to set default to v10-dev)
Latest tag: v10.0.0-beta.1
Commits since tag: 8
Working tree: clean
```

### Recent Commits (last 13)
```
5af7769 feat(finance): add dedicated FINANCE route with live market data fetchers
6e4ac39 feat(evidence): label EVIDENCE responses when fallback to non-trusted providers is used
61d7429 fix(evidence): reject TOC landing pages and off-topic content in trusted provider
17be065 docs: session handoff 2026-06-14 — production hardening complete
c7ec43d docs: create AGENTS.md and SESSION_CONTEXT.md for automatic session context
2fc14dd feat(security): fix medical follow-up gap and migrate to XDG paths
1e70996 feat(ops): XDG paths, DB migration, and operational runbooks
f0a2184 feat(ops): health check CLI and circuit breakers for search backends
6fe47b7 docs: add CHANGELOG.md for v10.0.0-beta.1
a19a0aa feat(security): add Ollama health probe and SQLite permission hardening
b95656e chore(prod): add Makefile, environment validator, VERSION, and LUCY_ROOT
3285850 docs: rewrite architecture report for v10 and remove stale session handoffs
ac40607 test: update expectations for new model defaults, routing behavior, and bridge architecture
bff0e38 feat(ui): consolidate HMI backend wrappers and remove legacy runtime bridge
709b1a0 feat(models): make background learning user-feedback-only and validate embedding index
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
    ▼          ▼          ▼          ▼
  LOCAL     AUGMENTED   WEATHER     NEWS
 (Ollama)  (Web+LLM)   (API)     (RSS)
```

### Four-Stage Routing Pipeline
1. **Structural safety** — empty/hostile/conspiracy filtering
2. **Embedding k-NN** — MiniLM semantic similarity
3. **Keyword guards** — medical/vet/weather/news hard catches
4. **Confidence fallback** → `CLARIFY` or `UNKNOWN`

### Routes
`LOCAL` | `AUGMENTED` | `EVIDENCE` | `NEWS` | `WEATHER` | `TIME` | `URL_REFERENCE` | `CLARIFY` | `UNKNOWN`

### Safety Critical
- Medical/vet queries **must** route to `EVIDENCE` with trusted sources
- Follow-ups after medical EVIDENCE are guarded to not fall back to LOCAL
- High-stakes feedback (medical/vet/finance/legal) → `pending_review.jsonl`

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

1. **Origin default branch** is still `v9-dev` — change in GitHub settings
2. **Dependency lockfile** (`requirements-lock.txt`) not yet generated
3. **Pre-commit hooks** (`.pre-commit-config.yaml`) exist as plan but not installed
4. **GitHub release workflow** (`.github/workflows/release.yml`) not yet created
5. **Structured logging** — `print()` statements still in codebase; JSON logger planned
6. **AppImage / .deb packaging** planned but not implemented
7. **Ollama** runs unauthenticated on localhost — document hardening for multi-user machines
8. **Hardcoded absolute paths** still exist in tests and benchmarks (low priority — non-production code)

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

*Last updated: 2026-06-15T17:32:00Z*
*Session: added dedicated FINANCE route with live stock, FX, and net-worth fetchers plus source citations*
