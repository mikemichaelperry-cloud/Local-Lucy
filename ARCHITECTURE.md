# Local Lucy V10 — Complete System Architecture

**Generated:** 2026-06-02
**Version:** v10-dev
**Hardware:** RTX 3060 12GB, 31GB RAM, CPU+GPU hybrid
**Test Suite:** ~720 passed, 19 skipped, 0 failures
**Router:** HybridRouterV2 (MiniLM embedding k-NN + keyword guards)
**Models:** qwen3:14b via Ollama (local-lucy-fast default), Whisper GPU on-demand, Kokoro TTS CPU
**Branch:** v10-dev
**Git Remote:** github.com:mikemichaelperry-cloud/Local-Lucy

---

## Current Maturity

| Component | Status |
|-----------|--------|
| Core routing | Stable (Stage 9 complete) |
| Local answer generation | Stable |
| Memory system | SQLite-native, semantic retrieval |
| Trusted evidence | Direct-fetch fallback + live extraction |
| Voice pipeline | Code-complete, backend tests pass |
| HMI memory dialog | Code-complete, visually verified |
| SearXNG search | JSON API primary, HTML fallback |
| Ollama warmup | Recurring background ping implemented |

---

## Technology Stack

| Layer | Technology |
|-------|------------|
| LLM Backend | Ollama (qwen3:14b, ~14B params, 2048-token context, KV cache q8_0) |
| Embedding Router | MiniLM-L6-v2, 384-dim, k-NN (k=3), ~978 examples |
| UI/HMI | PySide6/Qt6 desktop application |
| Voice STT | whisper.cpp (GPU on-demand) |
| Voice TTS | Kokoro (CPU) with Piper fallback |
| Memory | SQLite (WAL mode) with Ollama embeddings for semantic search |
| Web Extraction | webclaw (Rust binary) + legacy HTMLParser fallback |
| Search | SearXNG (self-hosted on :8080) — JSON API primary |
| State | SQLite + JSON files + `.env` legacy files |
| Python | 3.10 (ui-v10 venv), 3.13 (kimi-cli) |
| GPU | RTX 3060 12GB — qwen3:14b ~9.8GB VRAM |

---

## Key Architectural Decisions

1. **Python-native path is authoritative** — Shell scripts deprecated; all routing in Python.
2. **Single-path router** — One router (`HybridRouterV2`), one decision.
3. **Medical/veterinary safety at 4+ levels** — policy, classifier pre-guard, embedding override, provider hardcoding.
4. **Memory is dual-track** — SQLite for structured data + text files for backward compatibility.
5. **Caching is aggressive** — Local model responses cached by SHA-256 key including model + SELF_KNOWLEDGE hash.
6. **Namespace isolation** — Every execution gets a unique namespace directory.
7. **Ollama warmup ping** — Background thread keeps model hot, eliminating ~2.7s cold start.

---

## Recent Changes (2026-06-02)

### Ollama Warmup Ping
- `_OllamaWarmupThread`: daemon thread pings Ollama every 5 min (empty prompt, `num_predict=0`)
- Auto-starts at module load via `main.py`
- Configurable via `LUCY_WARMUP_ENABLED`, `LUCY_WARMUP_INTERVAL_S`, `LUCY_WARMUP_KEEP_ALIVE`

### Bounded Content Length Guard
- `MAX_EXTRACT_CHARS_HARD_CAP = 3000` in `web_extract.py`
- Default `max_chars` reduced: 6000 → 2500
- Prevents fetched articles from overflowing the 2048-token context window

### SearXNG JSON API
- `searxng_search_json()` uses `/search?format=json`
- JSON-first with automatic HTML fallback
- SearXNG container restarted with `json` format enabled

### Deprecated Legacy Tests
- `test_router_contract_schema.sh` — deprecated (validates shell pipeline)
- `run_router_regression_gate.sh` — deprecated (validates shell pipeline)

---

## Weaknesses & Known Issues

### Critical
1. **SearXNG backends down** — Brave, DDG, Google all returning CAPTCHA. Mitigated by direct-fetch fallback.
2. **qwen3 privacy guardrails** — "Do I have any kids?" triggers model-level refusal. Unfixable without fine-tuning.

### High Priority
3. **Live voice end-to-end not tested** — Code-complete but never tested with real audio hardware.
4. **num_ctx stuck at 2048** — Needs hardware upgrade (RTX 3060 12GB at limit).

### Medium Priority
5. **Regex-based SearXNG HTML parsing** — Deprecated; JSON API is primary. HTML fallback remains for resilience.
6. **Structural noise stripper is whitelist-based** — Could use link-density / all-caps detection.

---

## Test Coverage

| Suite | Tests | Status |
|-------|-------|--------|
| Router unit (`tools/router_py/`) | 554 + 148 subtests | Pass |
| Memory (all 8 files) | 94 | Pass |
| Trusted evidence unit | 19 | Pass |
| Web extract | 16 | Pass |
| HMI offscreen | 35 | Pass |
| Shell integration | 6 | Pass |
| Models/router | 22 | Pass |

---

## Environment Variables

### Warmup
| Variable | Default | Purpose |
|----------|---------|---------|
| `LUCY_WARMUP_ENABLED` | `1` | Enable/disable Ollama warmup |
| `LUCY_WARMUP_INTERVAL_S` | `300` | Seconds between pings |
| `LUCY_WARMUP_KEEP_ALIVE` | `10m` | keep_alive passed to Ollama |

### Web Extract
| Variable | Default | Purpose |
|----------|---------|---------|
| `LUCY_WEB_EXTRACT_MAX_CHARS` | `3000` | Hard cap on fetched content chars |

---

## Git Status

**Branch:** `v10-dev`
**Latest commit:** `ce5a847` (2026-05-30)
**Uncommitted changes:** 31 modified files + 7 untracked files

---

*End of Architecture Summary*
