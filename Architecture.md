# Local Lucy V11 — Architecture

**Date:** 2026-07-13
**Version:** v11
**Branch:** v10-dev
**Scope:** English-only primary runtime

> This document describes **v11 as implemented**. Hebrew / Racheli support has been removed from the primary runtime; the standalone Hebrew assistant was archived separately on 2026-07-10.
>
> Latest commits on `v10-dev`: Gemma 4 12B integration + smart-routing bypass (`357ce55`), low-VRAM warning (`fce4aa4`), heartbeat retargeting + HMI recursion guard, and voice CUDA orchestration with rollback (`<this-session>`).

---

## 1. Overview

Local Lucy V11 is a privacy-first, locally-hosted AI assistant. The primary runtime is English-only. It keeps conversation history and persistent facts in a local SQLite database, and only reaches out to the internet when the router explicitly decides an answer needs live or externally sourced evidence.

**Core design goals**

- **Local-first:** Stable knowledge, reasoning, creative writing, coding, recipes, and personal/family questions are answered by an Ollama-hosted local LLM unless the user asks for verification or live data.
- **When in doubt, route out:** Medical, veterinary, financial-market, news, weather, time, travel, and current-event queries are routed to sourced external providers.
- **Evidence vs synthesis:** Wikipedia, trusted medical/vet/finance domains, official APIs, and RSS feeds are treated as evidence. OpenAI and Kimi are synthesis providers, not evidence sources themselves.
- **No evasion:** The system prompt and routing policy answer directly, avoid unnecessary disclaimers, and do not refuse personal/family questions.
- **Context guard:** Every piece of retrieved evidence and session-memory turn is checked for provenance, temporal relevance, entity collision, and answerability before it is injected into the LLM prompt.
- **User-controlled learning:** Only explicit feedback (`thumbs_up/down`, corrections) is ingested into the learning pipeline; there is no implicit continuous retraining.
- **Unified entry point:** Every surface (HMI, voice, web, CLI) funnels through `tools/router_py/main.py::run(...)`.

---

## 2. System Boundary

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              Local Lucy V11                               │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌───────────┐ │
│  │   HMI        │   │   Voice      │   │    Web      │   │    CLI    │ │
│  │  (PySide6)   │   │  PTT/STT/TTS │   │   adapter   │   │           │ │
│  └──────┬───────┘   └──────┬───────┘   └──────┬───────┘   └─────┬─────┘ │
│         │                  │                  │                 │       │
│         └──────────────────┴──────────────────┴─────────────────┘       │
│                                    │                                      │
│                           tools/router_py/main.py                         │
│                                    │                                      │
│         ┌──────────────┬───────────┴───────────┬──────────────┐          │
│         ▼              ▼                       ▼              ▼          │
│  ┌─────────────┐ ┌─────────────┐      ┌─────────────┐ ┌─────────────┐   │
│  │  Router     │ │  Execution  │      │   Memory    │ │   State /   │   │
│  │  (classify) │ │   engine    │      │   service   │ │   feedback  │   │
│  └──────┬──────┘ └──────┬──────┘      └─────────────┘ └─────────────┘   │
│         │               │                                               │
│         ▼               ▼                                               │
│  ┌─────────────┐  ┌─────────────┐                                       │
│  │  Ollama     │  │  External   │  (Wikipedia, official APIs, news,    │   │
│  │  (local)    │  │  providers  │   weather, finance, time APIs)       │   │
│  └─────────────┘  └─────────────┘                                       │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Directory Layout

```
lucy-v10/
├── config/                    # Modelfiles, system prompts, policy configs
│   ├── Modelfile.local-lucy-llama31
│   ├── Modelfile.local-lucy-qwen3
│   ├── Modelfile.local-lucy-mistral
│   ├── Modelfile.local-lucy-fast
│   ├── Modelfile.local-lucy-stable
│   ├── Modelfile.local-lucy-mem
│   ├── evidence_policy.yaml
│   ├── trusted_domains.yaml
│   ├── url_map.yaml
│   ├── latency_optimizations.env
│   └── quarantined/           # Removed/disabled artifacts (e.g., old persona variants)
├── models/router/             # Fine-tuned MiniLM router, examples, learner
│   ├── hybrid_router_v2.py
│   ├── comprehensive_examples.json
│   ├── finetuned_minilm/
│   ├── background_learner.py
│   └── pending_review.jsonl
├── tools/router_py/           # Core execution engine (Python-native)
│   ├── main.py
│   ├── classify.py
│   ├── policy_router.py
│   ├── execution_engine.py
│   ├── local_answer.py
│   ├── model_selector.py
│   ├── context_guard.py
│   ├── feedback_buffer.py
│   └── providers/
├── tools/router/core/         # Semantic interpreter / intent classifier
│   └── intent_classifier.py
├── tools/memory/              # SQLite memory service
│   └── memory_service.py
├── tools/voice/               # Whisper STT, Kokoro/Piper/Edge TTS
│   ├── whisper_worker.py
│   ├── tts_adapter.py
│   └── voices/
├── ui-v10/                    # PySide6 desktop HMI
│   ├── app/panels/
│   └── app/services/runtime_bridge.py
├── web_adapter/               # Optional stateless HTTP API
│   └── server.py
├── tests/                     # Regression cases, golden responses
├── docs/                      # Handoffs, GPU allocation notes
└── START_LUCY.sh              # Desktop shortcut entry point
```

---

## 4. Request Pipeline

1. **Ingest** — `main.run(query, attachments, session_id, overrides)`
2. **Feedback detection** — Corrections and thumbs-up/down short-circuit to the feedback buffer / background learner.
3. **Gemma 4 smart-routing bypass (optional)** — If `gemma4_smart_routing` is enabled and the active model is a `gemma4:*` tag, ordinary queries short-circuit to `LOCAL` without running `classify_intent()` or `select_route()`. Explicit route prefixes and existing news/evidence pattern fast paths still win.
4. **Classify & route** — `classify.classify_intent()` + `select_route()` produce a `RoutingDecision`.
5. **Resolve provider** — `provider_resolver` maps the route to a concrete provider plan.
6. **Execute** — `execution_engine` runs the plan in a sandboxed Python namespace.
7. **Guard context** — `context_guard` filters evidence and memory for relevance.
8. **Generate answer** — `local_answer` streams the final response from Ollama (or formats external provider output).
9. **Persist** — Turn is written to SQLite; feedback/state files are updated.

---

## 5. Routing & Classification

Routing is **deterministic-first, semantic-second**.

### 5.0 Gemma 4 Smart-Routing Bypass

When the HMI toggle `gemma4_smart_routing` is on and the selected model is `gemma4:*`, `tools/router_py/request_pipeline.py` constructs a minimal `LOCAL` `RoutingDecision` directly. This skips the policy router, embedding router, and intent classifier for ordinary queries. It preserves:

- Explicit route prefixes (`news:`, `evidence:`, `augmented:`).
- Existing news/evidence pattern fast paths (`latest news about ...`, `evidence for ...`).
- Execution-engine guardrails (tool authorization, permissions, etc.).

The bypass is off by default; non-Gemma models always use the full router stack.

### 5.1 Policy Router (`tools/router_py/policy_router.py`)

An ordered set of regex/heuristic gates runs before the embedding model. Key gates include:

| Gate | Example trigger | Route |
|------|-----------------|-------|
| `hostile_override` | Jailbreak / authority-bypass attempts | `LOCAL` |
| `personal_family` | "How old is my daughter?" | `LOCAL` |
| `recreational_pet` | "Should I walk my dog?" | `LOCAL` |
| `medical_vet` | "Side effects of metformin", "My cat is limping" | `EVIDENCE` |
| `finance` | "TSLA price", "EUR to USD" | `FINANCE` |
| `time` | "What time is it in Tokyo?" | `TIME` |
| `weather` | "Weather in London" | `WEATHER` |
| `news` | "Latest Israel news" | `NEWS` |
| `evidence_request` | "Cite your sources" | `AUGMENTED` (evidence required) |
| `conflict_analysis` | "Will Russia win in Ukraine?" | `AUGMENTED` |
| `public_figure_age` | "How old is Bill Clinton?" | `AUGMENTED` |
| `recipe` | "Best chocolate cake recipe" | `AUGMENTED` |
| `travel_tourism` | "Places to visit in Japan" | `AUGMENTED` |
| `current_information` | "Current president of France" | `AUGMENTED` |
| `specific_entity_fact` | "Who is Ada Lovelace?" | `AUGMENTED` |
| `factual_lookup` | "What is the capital of France?" | `AUGMENTED` |
| `memory_followup` | "What did we discuss earlier?" | `LOCAL` |
| `local_reasoning` | Opinions, hypotheticals | `LOCAL` |

### 5.2 Hybrid Router V2 (`models/router/hybrid_router_v2.py`)

If no policy gate fires, the query goes to a **fine-tuned MiniLM sentence-transformer with a classifier head**. It returns a route with confidence and confidence margin; low-confidence or near-tie results fall back to `LOCAL` or `CLARIFY` rather than guessing.

### 5.3 `classify.py` Guards

After the policy router / embedding router, `classify.py` applies additional safety/context guards:

- **Continuation follow-up inheritance** — "Tell me more", "more details", "elaborate" inherit the route of the prior exchange if it was an evidence/external route.
- **Medical/veterinary follow-up guard** — Short ambiguous follow-ups ("why?", "is it safe?") after an `EVIDENCE` medical/vet answer stay on `EVIDENCE`/`AUGMENTED`.
- **Memory follow-up guard** — Explicit memory-recall phrases override live-data routes back to `LOCAL` when session memory is enabled.
- **Short-query guard** — Utterances like "thanks", "ok", "wrong" stay `LOCAL`.
- **Hostile override** — Adversarial probes are forced `LOCAL`.

### 5.4 Route Labels

`LOCAL`, `AUGMENTED`, `EVIDENCE`, `NEWS`, `WEATHER`, `TIME`, `FINANCE`, `CLARIFY`, `MEMORY_FOLLOWUP`, `TRAVEL_TOURISM`, `LOCAL_REASONING`, `EPHEMERAL`.

---

## 6. Provider & Evidence Layer

Providers are Python modules loaded and executed inside `execution_engine.py`.

| Route | Primary provider | Notes |
|-------|------------------|-------|
| `LOCAL` | Ollama local model | Injects session memory + persistent facts |
| `AUGMENTED` | Wikipedia / OpenAI / Kimi chain | Sourced external answer; Wikipedia is evidence, OpenAI/Kimi synthesise |
| `EVIDENCE` | Trusted evidence (Wikipedia + allowlisted domains) | Medical/vet/finance safety route |
| `NEWS` | RSS news provider | Current headlines with recency scoring and source cross-check |
| `WEATHER` | Weather provider | Live forecast |
| `TIME` | Time API | Current time by location |
| `FINANCE` | Finance provider | Live market data with citations and freshness checks |

Evidence source quality is constrained by `config/trusted_domains.yaml` and `config/url_map.yaml`. Medical and veterinary queries require trusted evidence; they cannot be overridden to a generative provider.

### 6.1 News Provider Improvements

- **Recency scoring:** RSS `pubDate` is parsed; articles older than 7 days are dropped unless the query contains history markers (`history`, `in 20xx`, `during`, `past`, `old`).
- **Source cross-check:** When more than one feed is available for a region/topic, top items from 2–3 sources are included. If titles/snippets disagree, the result carries `disagreement=True`.

### 6.2 Evidence Freshness & Fallback

- Medical/veterinary/finance evidence is checked for freshness. If the source date/`source_age_days` is older than 365 days, `fresh=False` is set and confidence is reduced.
- If a live evidence fetch fails or returns no usable result, the provider returns a structured fallback dict with `fallback=True` and `suggested_action="local_with_caveat"`. The execution engine answers from local knowledge with the prefix: "Live sources are unavailable; here is what I know:".

---

## 7. Execution Engine

`tools/router_py/execution_engine.py` is the central dispatch layer:

- **Python-native only** as of 2026-07-09: the legacy shell fallback path and the `use_python_path` toggle were removed. Callers (`ui-v10/app/services/runtime_bridge.py`, `tools/router_py/request_pipeline.py`) invoke Python directly.
- Builds a Python execution plan from the resolved route.
- Runs in an isolated namespace.
- Loads relevant memory context.
- Calls the appropriate provider function.
- Filters evidence and memory through `context_guard`.
- Formats the response and writes structured state updates via `StateWriter`.
- On failure, escalates to clarification or local reasoning rather than crashing.

The file shrank from ~3,900 lines to ~2,216 lines after the shell removal, reducing surface area for dual-path bugs.

---

## 8. Local Answer & Model Selection

### 8.1 Local Answer (`tools/router_py/local_answer.py`)

- Async Ollama client with streaming support.
- Builds the final prompt from the selected Modelfile, session memory, persistent facts, and any fetched external context.
- Enforces first-person self-reference and self-knowledge boundaries through the system prompt.
- Detects thinking models (Qwen3, DeepSeek-R1, Gemma 4, etc.) and applies a token-budget multiplier so reasoning tokens do not swallow the visible response.
- Provides `get_gpu_free_vram_mb()` for HMI resource warnings.
- **Model identity mapping:** `_MODEL_IDENTITIES` maps each selectable backend alias (e.g. `local-lucy-llama31`, `gemma4:12b-it-qat`) to a human-readable `(ollama_name, params)` tuple. The self-knowledge system prompt is built from this map so identity answers always describe the model that is actually loaded.
- **Heartbeat retargeting:** The background Ollama keep-alive heartbeat and the recurring warmup thread both read the authoritative `current_state.json` model on every cycle and abort if it no longer matches their target. This prevents a stale heartbeat from re-loading a previously selected model after a user switch or profile reload.
- **Post-request warmup targets the effective model:** After a request, `runtime_bridge.py` keeps warm the model that actually answered, not the automatic selector's shadow recommendation, so the active model is not evicted.
- **Profile reload preserves model selection:** `tools/runtime_profile.py` resets only `profile` and `status`; it does not overwrite the user-selected model in `current_state.json`.
- **Context-follow-up memory preservation:** `local_answer.py` detects obvious conversational continuations ("what about...", "how about...", etc.) and keeps the recent session memory unfiltered, with a prompt instruction telling the model to answer in context.

### 8.2 Model Selector (`tools/router_py/model_selector.py`)

The UI exposes an **Auto** default. In shadow mode, the selector automatically chooses the most appropriate local model by query bucket. Manual overrides remain available for power users. `gemma4:12b-it-qat` is available as an optional reasoning/multimodal model.

**Benchmarking:** `ui-v10/model_comparison_benchmark_v2.py` measures clean-slate cold-start and warm-run latency for every selectable mode (`auto`, `local-lucy-llama31`, `gemma4:12b-it-qat`). It unloads Ollama between modes, disables the repeat cache, and writes a JSON report plus a Markdown summary to the Desktop.

### 8.3 VRAM Management

- The HMI warns when Gemma 4 is selected on a GPU with <12 GB free VRAM.
- Local Lucy does not force GPU-only execution; Ollama/llama.cpp may offload layers to system RAM when VRAM is exhausted.
- The runtime evicts other loaded Ollama models when switching models, keeping only the active model in VRAM.

### 8.4 Default Modelfile (`config/Modelfile.local-lucy-llama31`)

```modelfile
FROM llama3.1:8b
PARAMETER num_ctx 8192
PARAMETER num_thread 8
PARAMETER temperature 0.0
PARAMETER top_p 0.5
PARAMETER repeat_penalty 1.2
SYSTEM """
You are Local Lucy, an AI running locally on the user's computer via Ollama.
Rules:
- Speak in first person as "I". Never use third person.
- Do not fabricate facts. Say "insufficient data" or "unknown" when uncertain.
- Answer directly and factually. Avoid generic disclaimers and boilerplate.
- Do not refuse questions about the user, their family, or their pets.
- Separate facts, assumptions, inferences, and opinions clearly.
- When using retrieved context, cite the source.
"""
```

### 8.5 Voice Mode & CUDA Orchestration

Voice mode uses **Whisper** for STT and **Kokoro** (with Piper/Edge fallbacks) for TTS. On a 12 GB RTX 3060, leaving both voice models resident on the GPU together with the active LLM can exceed VRAM, so voice CUDA orchestration loads and unloads them sequentially.

**Feature flag:** `LUCY_VOICE_CUDA_ORCHESTRATION`
- Default: **unset / `0`** — previous behavior (CPU-bound voice, models cached in RAM).
- Set to `1` to enable sequential GPU loading.

**Sequence when enabled:**
1. PTT pressed → load Whisper on CUDA for STT.
2. Transcription done → release Whisper before the LLM request starts.
3. LLM response ready → load Kokoro on CUDA for TTS.
4. TTS done → release Kokoro.

**Implementation:**
- `tools/runtime_voice.py` exposes `_ensure_stt_gpu()`, `_release_stt()`, `_ensure_tts_gpu()`, `_release_tts()` and gates them with `_cuda_orchestration_enabled()`.
- `tools/voice/backends/kokoro_backend.py` adds `clear_pipeline_cache()` so Kokoro can be unloaded on demand.
- `ui-v10/app/services/runtime_bridge.py` skips Kokoro prewarm and only prewarms Whisper on GPU when the flag is on.

**Rollback:** unset `LUCY_VOICE_CUDA_ORCHESTRATION` or set it to `0` and restart Local Lucy.

---

## 9. Context Guard (`tools/router_py/context_guard.py`)

Every retrieved evidence item and memory turn is scored before being injected into the prompt:

- **Provenance:** Wikipedia, medical, finance, weather, and news sources score higher; generated text and memory are damped.
- **Temporal:** Current-fact queries penalise evidence older than 30 days (weather and time sources are exempt).
- **Entity collision:** A named entity in the query that does not appear in the evidence reduces the score.
- **Answerability:** Evidence with no content-word overlap with the question is heavily discounted.

If relevance is below threshold, the evidence/turn is dropped.

---

## 10. Memory, Feedback & Learning

### 10.1 Session Memory (`tools/memory/memory_service.py`)

- SQLite tables: `conversation_turns`, `session_summaries`, `summary_embeddings`, `archived_turns`, `session_metadata`.
- Last few turns are prepended to the prompt.
- Session summaries are embedded with MiniLM for long-context retrieval.
- Personal/family queries suppress noisy session memory when explicit persistent facts are available.

### 10.2 Persistent Memory

- SQLite table: `persistent_facts`.
- Stores approved facts (family members, pets, preferences, addresses).
- MiniLM embeddings pre-computed at storage time; semantic retrieval threshold ~0.35.

### 10.3 Feedback Buffer (`tools/router_py/feedback_buffer.py`)

- Ring buffer of recent exchanges.
- Used for fast correction replay and continuation-follow-up inheritance.

### 10.4 Background Learner (`models/router/background_learner.py`)

- Ingests **explicit user feedback only**.
- Safety gate prevents auto-learning of medical/vet/evidence routes without human review.
- Versioned examples go to `comprehensive_examples.json`; high-stakes or conflicting feedback goes to `pending_review.jsonl`.

---

## 11. UI / HMI & Web Adapter

### 11.1 Desktop UI (`ui-v10/`)

The HMI has been simplified to two views:

- **Default view:** Conversation history, input, memory/voice toggles, and the Auto model selector.
- **Engineering panel:** Exposes route diagnostics, provider selectors, augmentation policy, learner controls, and structured logs.

`app/services/runtime_bridge.py` calls Python functions directly (`main.run(...)`, `execute_plan_python(...)`); no shell indirection.

The control panel blocks checkbox signals while programmatically refreshing a toggle's checked state (e.g. `gemma4_smart_routing`), preventing a state-change signal from looping back into the backend action handler.

### 11.2 Runtime Control

- `START_LUCY.sh` — desktop shortcut entry point.
- `tools/runtime_control.py` / `tools/runtime_request.py` — process lifecycle and local API access.
- `config/latency_optimizations.env` — caching, timeout, and GPU knobs.

### 11.3 Web Adapter (`web_adapter/server.py`)

- Optional aioHTTP server, stateless.
- Gated by `LUCY_WEB_ENABLED=1`.
- Default bind: `127.0.0.1:8765`; supports LAN/Tailscale binding with token auth.
- REST endpoints; covered by `web_adapter/test_web_adapter.py`.

---

## 12. Configuration Reference

| File / Variable | Purpose |
|-----------------|---------|
| `.env.example` | API keys, feature flags, endpoints |
| `config/evidence_policy.yaml` | When external evidence is allowed/required |
| `config/conversation_profile.json` | Default persona / tone |
| `config/trusted_domains.yaml` | Allowlisted evidence sources |
| `config/url_map.yaml` | Source-specific URL overrides |
| `config/latency_optimizations.env` | Caching, timeout, GPU knobs |
| `LUCY_SESSION_MEMORY=1` | Enable session memory |
| `LUCY_ENABLE_INTERNET=1` | Enable external providers |
| `LUCY_WEB_ENABLED=1` | Enable HTTP adapter |
| `OLLAMA_FLASH_ATTENTION=1` | GPU optimization |
| `OLLAMA_KV_CACHE_TYPE=q8_0` | GPU optimization |

---

## 13. Test Structure

| Location | Coverage |
|----------|----------|
| `tests/` | Golden responses, regression cases, specific entity fact gate |
| `tools/router_py/test_*.py` | Routing, policy, classification, finance, medical, news, edge cases, evidence provider |
| `tools/tests/` | Memory service, end-to-end comprehensive tests |
| `tools/voice/tests/` | TTS fallback, voice utilities |
| `ui-v10/tests/` | Off-screen HMI tests |
| `web_adapter/test_web_adapter.py` | HTTP adapter tests |

Run the routing/policy suite:

```bash
cd /home/mike/lucy-v10/tools/router_py
python3 -m pytest test_policy_router.py test_classify.py test_routing_edge_cases.py test_policy.py test_finance_routing.py test_medical_evidence_routing.py test_news_synthesis_routing.py test_augmented_auto_routing.py test_news_provider.py test_evidence_provider.py -v
```

---

## 14. What Changed for V11

| V10 claim | V11 reality |
|-----------|-------------|
| Hebrew / Racheli persona in primary runtime | **Removed** from the primary runtime on 2026-07-10; English-only |
| Five-model manual selector | **Auto default** with automatic model selection in shadow mode |
| Evidence could include OpenAI/Kimi as sources | **Wikipedia/official APIs are evidence**; OpenAI/Kimi are synthesis only |
| Local-first with broad local fallback | **Local-first strengthened**; "when in doubt, route out" for high-stakes/current facts |
| Context validation absent | **Context guard** added: provenance, temporal, entity, answerability checks |
| Full-featured default HMI | **Simplified default view** + optional Engineering panel |
| News fetched from all feeds equally | **Recency scoring** and **source cross-check** with disagreement flag |
| Evidence freshness not checked | **Freshness check** for medical/vet/finance evidence |
| Live evidence failures returned clarification | **Graceful fallback** to local knowledge with `local_with_caveat` |

---

*End of architecture document.*
