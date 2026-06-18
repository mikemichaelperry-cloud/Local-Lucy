# Changelog

All notable changes to Local Lucy are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Optional web interface at `web_adapter/` for remote text access to Local Lucy.
  - Standalone entry point: `LUCY_WEB_ENABLED=1 python -m web_adapter`
  - Single-page HTML UI with status, model selector, and chat-style input/output
  - Endpoints: `GET /`, `GET /api/status`, `GET /api/models`, `POST /api/ask`
  - Stateless by default; isolated from PyQt HMI session memory
  - Request-scoped model selection validated against configured models
  - Basic/Bearer authentication; mandatory for non-loopback binds
- `docs/web_interface.md` documentation and `web_adapter/test_web_adapter.py` tests.

### Changed
- GitHub release workflow no longer builds the experimental AppImage automatically; the build script is retained for manual use.
- Regression tests now skip cleanly when Ollama is unavailable (`skip_without_ollama` fixture).
- Semantic regression skips comparison when goldens were recorded under a different model.
- `make lint` now enforces both `ruff` and `mypy`.
- `pyproject.toml` testpaths and `Makefile` lint target include `web_adapter/`.

### Fixed
- Full test suite green: `942 passed, 19 skipped`.
- Keel loader, whisper fallback, model selector, state-store, and pytest collection issues resolved.

### Security
- Web adapter defaults to loopback binding and requires authentication for LAN/Tailscale exposure.
- No secrets embedded in source, HTML, URLs, or logs.

### Deprecated
- Legacy transition flags `LUCY_ROUTER_PY` and `LUCY_EXEC_PY` are no longer needed; Python router/execution are the default in V10.
- Legacy keyword-router rollback `LUCY_ROUTER_LEGACY_PRIMARY=1` is deprecated and non-functional; the embedding router is the sole authority.

## [10.0.0-beta.1] - 2026-06-14

### Added
- Dedicated `FINANCE` route with live market-data fetchers and source citations.
  - Exchange rates via `exchangerate-api.com`
  - Crypto prices via CoinGecko
  - Stock/index quotes via Yahoo Finance with web-search fallback on rate-limit
  - Net-worth lookups via web search restricted to trusted finance sources
- `tools/router_py/test_finance_routing.py` covering route detection, provider helpers, and execution labeling.
- Production hardening: CI fixes, gitignore rewrite, version alignment to 10.0.0-beta.1
- SearXNG secret rotation with auto-generation via `services/searxng/start.sh`
- Root `Makefile` with `install`, `test`, `lint`, `run`, `clean`, `check-env` targets
- `scripts/check_environment.py` for pre-flight validation of Ollama, models, CUDA, deps
- `VERSION` file and `__version__` in `tools.router_py.__init__`
- `LUCY_ROOT` constant derived from `__file__` for portability
- Ollama health probe in `START_LUCY.sh` — fails fast with clear error if daemon unreachable
- SQLite permission hardening (`0o600`) for `lucy_state.db` and `memory.db`

### Changed
- `SESSION_CONTEXT.md` and `ARCHITECTURE.md` now document the `FINANCE` route and its data sources.
- Default local model migrated to `llama3.1:8b` across all entry points
- Embedding-first routing is now the sole authority (keyword fortress removed)
- Background learner ingests only explicit user feedback (auto-feedback is telemetry-only)
- HMI backend wrappers consolidated to pure re-exports from `router_py`
- Removed deprecated `runtime_bridge_consolidated.py` (-779 lines)

### Fixed
- CI branch triggers now target `[main, v10-dev]`; removed all `|| true` suppressions
- `.gitignore` updated for v10 runtime artifacts
- `pyproject.toml` and `pytest.ini` unified into single pytest config
- Medical/vet safety pre-guard runs before personal/family guard

### Security
- Rotated committed SearXNG secret key
- Added `settings.yml.example` and `.gitignore` for live SearXNG settings
- SQLite databases created with restrictive permissions
- Ollama startup validation prevents silent hangs

## [8.x.x] and earlier

See git history for v8 and v9 changelogs.
