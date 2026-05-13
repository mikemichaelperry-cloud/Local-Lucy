# Changelog

All notable changes to Local Lucy are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Schema migrations** — Versioned SQLite migration system using `PRAGMA user_version` with idempotent forward migrations and per-version transactions.
- **Auto-feedback trust tiers** — Separate thresholds for user (`LUCY_AUTO_LEARN_THRESHOLD=3`) and auto-feedback (`LUCY_AUTO_FEEDBACK_THRESHOLD=5`) with confidence capping at 0.5.
- **Voice PTT controller** — Async state machine with hold mode (press/release) and tap mode (double-tap), plus 8-second timeout guard.
- **Short-query routing guard** — Higher similarity threshold (0.90) for queries with ≤5 words to prevent embedding collapse misrouting.
- **Memory gate session propagation** — `_memory_routing_gate` now receives actual `session_id` instead of hardcoded `"default"`.
- **Feedback parser patterns** — New route correction patterns for "correct routing is X", "correct answer is X", and "it's X".

### Changed
- Consolidated `ui-v8/app/backend/router/core/` modules into `tools/router_py/` as the single source of truth.
- Removed legacy shell scripts (`tools/classify_query.sh`, `tools/evidence_answer.sh`, etc.) superseded by Python implementations.
- Stopped tracking runtime state files in git (`state/`, `logs/`, `feedback_buffer.json`).

### Fixed
- **Embedding collapse detection** — ModernBERT [CLS] embeddings collapsing for short personal queries (e.g., "Who is my dog?" → TIME at 0.994 similarity). Added two safety nets: embedding collapse fallback and no-keyword live-data fallback.
- **Feedback detection** — Standalone "Incorrect" at the start of utterances now triggers negative feedback patterns.
- **Route inference** — Semantic misroute inference for TIME/NEWS/WEATHER negative feedback when query lacks characteristic keywords.
- **Cross-device link error** — `save_index()` now uses `tmp_dir = Path(INDEX_PATH).parent` for atomic moves across filesystems.
- **Dedup persistence bug** — `learn_once()` now triggers save when examples are deduplicated (`all_examples != examples`).

## [8.0.0-alpha] — 2026-05-12

### Added
- **ModernBERT-base router** — Replaced sentence-transformers with ModernBERT-base for 768-dim [CLS] embeddings.
- **Self-learning kill switch** — `LUCY_LEARN_ENABLED` environment toggle.
- **Router index versioning** — Automatic backups in `models/router/versions/`.
- **Adversarial prompt testing** — 109 prompts across 13 categories with 0 crash tolerance.
- **Medical query heuristics** — High-risk medication detection and safe routing.
- **Contextual routing policy** — Follow-up query detection with conversation memory.

### Changed
- Migrated from v7 shell-based router to pure Python v8 router.
- Consolidated bridge architecture (`runtime_bridge_consolidated.py`).

### Fixed
- Provider priority resolution for fallback chains.
- Memory pipeline integration with SQLite.
- EVIDENCE route Wikipedia + web search aggregation.
- Multi-part prompt handling in augmented mode.
- aiohttp unclosed session warnings.

## [7.x] — 2026-02 to 2026-04

### Added
- Terminal chat interface (`lucy_chat.sh`).
- PySide6 desktop HMI.
- Voice pipeline with Whisper STT and Piper TTS.
- SQLite session memory.
- Keyword-based routing with guard rails.

### Security
- Runtime output guard for PII detection.
- Allowlist-based command execution.
- Semantic interpreter backend validation.

---

## Legend

- **feat** — New feature
- **fix** — Bug fix
- **docs** — Documentation
- **test** — Tests
- **chore** — Maintenance
- **refactor** — Code restructuring
