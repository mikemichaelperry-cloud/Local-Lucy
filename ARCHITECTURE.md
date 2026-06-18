# Local Lucy V10 — Comprehensive Architecture Report

**Date:** 2026-06-08
**For:** Kimi / ChatGPT / Any Future Agent
**Version:** v10-dev
**Branch:** `v10-dev`
**Hardware:** RTX 3060 12GB, 31GB RAM

---

## 1. Project Overview

Local Lucy v10 is a locally-hosted AI assistant running entirely on the user's machine. It combines a PySide6 desktop HMI, an optional HTTP web interface, a hybrid keyword/embedding router, persistent SQLite memory, voice input/output (Whisper STT + Kokoro TTS), and web-augmented answering via multi-backend search (DuckDuckGo primary, SearXNG fallback, Brave API optional).

**Core philosophy:** Facts only, no evasion, no political correctness. The AI does what the user asks.

**Hardware fallback:** Ollama auto-offloads GPU layers to CPU/RAM when VRAM is full. With 31 GB system RAM, any model can run entirely in RAM if needed.

---

## 2. Directory Structure

```
lucy-v10/
├── config/                  # Modelfiles, environment configs
│   ├── Modelfile.local-lucy-llama31   ← default
│   ├── Modelfile.local-lucy
│   ├── Modelfile.local-lucy-fast
│   ├── Modelfile.local-lucy-mistral
│   └── latency_optimizations.env
├── models/router/           # Embedding router, training data, auto-learn
│   ├── hybrid_router_v2.py
│   ├── background_learner.py          ← user-feedback only
│   ├── auto_feedback.py               ← telemetry only
│   ├── comprehensive_examples.json    ← 1,019 examples
│   └── pending_review.jsonl           ← human-review queue
├── tools/router_py/         # Python-native execution engine
│   ├── main.py
│   ├── local_answer.py
│   ├── classify.py                    ← router loading + exception logging
│   ├── policy.py
│   ├── execution_engine.py
│   └── execution_engine_state.py
├── tools/router/core/       # Semantic interpreter
│   └── semantic_interpreter.py
├── ui-v10/                  # PySide6 HMI (ONLY ui-v10, NO ui-v7 fallback)
│   ├── app/panels/control_panel.py    ← 4-model selector
│   ├── app/services/runtime_bridge.py ← v10 isolation enforced
│   └── tests/                         # offscreen HMI tests
├── runtime/voice/           # whisper.cpp, Kokoro TTS
├── memory/                  # SQLite memory service
├── state/                   # Runtime state JSON
├── data/tubes/              # Web extraction pipelines
├── tests/                   # Golden responses, regression cases
├── test_reports/            # Test output reports
└── docs/                    # Session handoffs, architecture
```

---

## 3. Model Configuration

### Default: `local-lucy-llama31` (llama3.1:8b)

```modelfile
FROM llama3.1:8b
PARAMETER num_ctx 4096
PARAMETER num_thread 8
PARAMETER temperature 0.0
PARAMETER top_p 0.5
PARAMETER repeat_penalty 1.2
SYSTEM """
You are Local Lucy, an AI running locally on the user's computer via Ollama.
Rules:
- Speak in first person as "I". Never use third person.
- Do not fabricate facts. Say "I don't know" when uncertain.
- Answer directly and factually. Never apologize, hedge, or add disclaimers.
- Do not refuse questions about the user, their family, or their pets.
- Facts only. Nothing else.
"""
```

**Why this model:**
- Zero refusals on personal/family queries (unlike qwen3)
- ~3× faster cold-start than qwen3:14b
- ~8.5 GB VRAM usage leaves 3.5 GB headroom for Whisper GPU
- 4096-token context window (vs 2048 for qwen3/mistral)
- Not Chinese-regulatory-tuned; follows system prompts literally

### Legacy Options (still selectable in HMI)

| Model | Base | Context | VRAM | Notes |
|-------|------|---------|------|-------|
| `local-lucy` | qwen3:14b | 2048 | ~9.3 GB | Has privacy guardrails; refuses personal queries |
| `local-lucy-fast` | qwen3:14b | 2048 | ~9.3 GB | Identical to local-lucy; name is misleading |
| `local-lucy-mistral` | mistral-nemo | 2048 | ~8.5 GB | Less constrained, drier/encyclopedic style |

---

## 4. Routing Architecture

```
User Query
    ↓
[Keyword Guards] — Medical? Vet? News? Weather? Finance? → Hard route
    ↓
[HybridRouterV2] — MiniLM embedding k-NN (k=3) + keyword boost
    ↓
RoutingDecision: LOCAL | AUGMENTED | NEWS | WEATHER | EVIDENCE | FINANCE | URL_REFERENCE | CLARIFY | UNKNOWN
    ↓
[ExecutionEngine] — Route-specific handler
    ↓
Response
```

### FINANCE Route (Added 2026-06-15)

Live market-data route with source citations, distinct from `LOCAL` personal-finance reasoning.

| Query Type | Primary Source | Fallback |
|---|---|---|
| Exchange rates (`EUR to USD`) | `exchangerate-api.com` | — |
| Crypto (`Bitcoin price`) | CoinGecko | — |
| Stocks/indices (`TSLA`, `S&P 500`) | Yahoo Finance | Web search |
| Net worth (`Elon Musk net worth`) | Web search (trusted finance sources) | — |

Personal-finance reasoning queries (budgeting, investing advice, tax planning) continue to route `LOCAL`.


### Router Loading (Fixed 2026-06-08)
- `_get_router()` in `classify.py` now logs all exceptions to stderr
- Previously had bare `except Exception:` that silently swallowed errors
- Common failure: missing `pytz` → `sentence_transformers` import chain fails

### Safety Layers (Medical/Vet/Finance)
1. **Keyword guard** — Pre-router regex catches critical medical/vet/finance terms
2. **Policy check** — `policy.requires_evidence_mode()` for medical_context, body_symptom, etc.
3. **Embedding override** — If router misroutes, evidence/finance mode is forced
4. **Provider hardcoding** — Medical queries always route to trusted evidence; finance market-data queries route to `FINANCE` with source citations

### Memory Follow-up Guard (Fixed 2026-06-07)
- Short follow-ups like "why?" after medical answers no longer override EVIDENCE back to LOCAL
- EVIDENCE routes are preserved from memory follow-up override

---

## 5. Search Architecture (Multi-Backend, 2026-06-08)

```
User Query (AUGMENTED/NEWS/WEATHER/EVIDENCE/FINANCE)
    ↓
[search_web.py]
    ├─→ DuckDuckGo direct (free, no API key) ← PRIMARY
    ├─→ SearXNG JSON (local Docker, 127.0.0.1:8080)
    ├─→ SearXNG HTML scrape fallback
    └─→ Brave Search API (optional, requires key)
    ↓
[Domain allowlist filter] — trust_catalog.yaml tiers 1+2
    ↓
[web_extract.py] — webclaw → curl fetch → HTMLParser
    ↓
Response text (truncated to 3000 chars)
```

### Backend Priority (configurable)
Default: `duckduckgo,searxng_json,searxng_html,brave`

Set `LUCY_SEARCH_BACKEND_PRIORITY` to reorder or disable backends.
Set `LUCY_BRAVE_API_KEY` to enable Brave Search (free tier: 2,000 queries/month).

### Why DuckDuckGo primary?
- No API key required
- No CAPTCHA/rate-limit issues (unlike SearXNG scraping Google/Bing)
- Returns clean structured results
- For personal use (~50-100 queries/day), well within limits

---

## 6. Memory Architecture

### Persistent Memory (SQLite)
- **Table:** `persistent_facts` — approved facts (family, pets, preferences)
- **Embeddings:** MiniLM-L6-v2 (384-dim) pre-computed at storage time
- **Retrieval:** `get_relevant_persistent_facts()` — semantic search with threshold 0.35
- **Fallback:** `_load_family_facts_direct()` — raw SQLite SELECT for family category

### Session Memory
- **SQLite:** `chat_turns` table per session
- **Injection:** Last 3 turns prepended to prompt
- **Suppressor guard:** Session memory is cleared for personal/family queries when explicit persistent facts are loaded

---

## 7. Auto-Learn System

### Signal Sources

| Source | Destination | Ingested? |
|--------|-------------|-----------|
| User feedback | `comprehensive_examples.json` | **Yes** (after safety gate) |
| Auto-feedback heuristics | `auto_feedback.jsonl` | **No** — telemetry only |
| Router decision logs | `router_logs/` | **No** — telemetry only |
| High-stakes feedback | `pending_review.jsonl` | **No** — human review required |
| Route conflicts | `pending_review.jsonl` | **No** — human review required |

### Safety Gate
- `route == "EVIDENCE"` → always review
- `policy.requires_evidence_mode()` returns medical/vet/finance/legal → review

---

## 8. Voice Pipeline

```
PTT Press → Record Audio → Whisper.cpp (GPU if available) → Transcript
    → Router → LLM → Kokoro TTS (CPU) → Audio Out
```

**Voice model:** `local-lucy-llama31` (was hardcoded to `local-lucy-fast`, fixed 2026-06-07)

**TTS:** Kokoro on CPU (forced via `LUCY_VOICE_KOKORO_DEVICE=cpu` to prevent GPU OOM)

---

## 9. Environment Isolation (Fixed 2026-06-08)

**CRITICAL:** `ui-v10/.venv` is the ONLY Python environment. No `ui-v7` fallback.

**PYTHONPATH:** `tools:ui-v10/app` (user site `~/.local/lib/python3.10/site-packages` EXCLUDED)

**Launcher scripts:**
- `START_LUCY.sh` — Desktop shortcut entrypoint
- `tools/start_local_lucy_v9.sh` — Legacy terminal launcher

Both must only reference `ui-v10/.venv/bin/python3`.

**Optional web interface:**
- `LUCY_WEB_ENABLED=1 python -m web_adapter` — Standalone HTTP adapter
- Binds `127.0.0.1:8765` by default; supports LAN/Tailscale binding with token auth.
- The adapter is a thin I/O layer over `tools/router_py/main.py::execute_plan_python()` and is stateless by default.

---

## 10. Key Files for Agents

| File | Purpose |
|------|---------|
| `models/router/hybrid_router_v2.py` | Core routing logic |
| `models/router/background_learner.py` | Learning pipeline |
| `tools/router_py/classify.py` | Intent classification, router loading |
| `tools/router_py/local_answer.py` | Local answer generation |
| `tools/router_py/execution_engine.py` | Route execution |
| `tools/router_py/policy.py` | Evidence mode policy |
| `ui-v10/app/services/runtime_bridge.py` | HMI ↔ backend bridge |
| `web_adapter/server.py` | Optional HTTP/web UI adapter |
| `config/Modelfile.local-lucy-llama31` | Default model config |
| `memory/memory_service.py` | SQLite memory operations |
| `pytest.ini` | Test config (asyncio_mode = auto) |

---

## 11. Environment Quick Reference

```bash
# Python (venv only)
~/lucy-v10/ui-v10/.venv/bin/python3

# PYTHONPATH (isolated)
export PYTHONPATH="${LUCY_ROOT}/ui-v10/app"

# Default model
export LUCY_LOCAL_MODEL=local-lucy-llama31

# Features
export LUCY_ROUTER_PY=1
export LUCY_EXEC_PY=1
export LUCY_ENABLE_INTERNET=1
export LUCY_SESSION_MEMORY=1

# Optional web interface
export LUCY_WEB_ENABLED=1
export LUCY_WEB_HOST=127.0.0.1
export LUCY_WEB_PORT=8765
# export LUCY_WEB_AUTH_TOKEN=<required for non-loopback binds>

# GPU optimization
export OLLAMA_FLASH_ATTENTION=1
export OLLAMA_KV_CACHE_TYPE=q8_0
```

---

*End of Comprehensive Architecture Report*
