# Changelog

All notable changes to Local Lucy are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [10.0.0-beta.1] - 2026-06-14

### Added
- Production hardening: CI fixes, gitignore rewrite, version alignment to 10.0.0-beta.1
- SearXNG secret rotation with auto-generation via `services/searxng/start.sh`
- Root `Makefile` with `install`, `test`, `lint`, `run`, `clean`, `check-env` targets
- `scripts/check_environment.py` for pre-flight validation of Ollama, models, CUDA, deps
- `VERSION` file and `__version__` in `tools.router_py.__init__`
- `LUCY_ROOT` constant derived from `__file__` for portability
- Ollama health probe in `START_LUCY.sh` — fails fast with clear error if daemon unreachable
- SQLite permission hardening (`0o600`) for `lucy_state.db` and `memory.db`

### Changed
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
