# Local Lucy V10 — Architecture

**Date:** 2026-07-04
**Version:** v10
**Branch:** main / v10-dev
**Hardware target:** RTX 3060 12 GB (current), RTX 3090/5090 (planned upgrades)

---

## ⚠️ V11 Migration Notice

This document describes the **current V10 implementation**. It is **descriptive, not normative for V11**. Several components documented here are scheduled for correction or isolation in Phase 0 of the V11 roadmap (`docs/superpowers/plans/2026-07-05-local-lucy-v11-roadmap.md`):

- **Hebrew / Racheli persona support** is being separated from the primary Local Lucy runtime.
- **Evidence versus synthesis** handling will change: Wikipedia, official APIs, and trusted domains remain evidence sources; OpenAI and Kimi are synthesis providers, not evidence sources themselves.
- **Local-first routing** will be strengthened: stable basic facts, recipes, coding, opinion, and creative writing should stay LOCAL unless the user requests verification or live data.
- **Prompt policy** will be revised to remove contradictions ("say I don't know" vs "never hedge" vs "facts only").
- **Context validation** will be added before any source is injected into the LLM prompt.

When implementing V11, follow the revised V11 roadmap, not this document as a specification. During Phase 0, this document will be frozen as `Architecture_V10_Current_State.md` and `Architecture.md` will become the evolving normative V11 architecture.

---

## 1. Overview

Local Lucy V10 is a privacy-first, locally-hosted AI assistant. It runs entirely on the user's machine, keeps conversation history and persistent facts in a local SQLite database, and only reaches out to the internet when the router explicitly decides an answer needs live or external evidence.

**Core design goals**

- **Local by default:** General knowledge, reasoning, creative writing, coding, and personal/family questions are answered by an Ollama-hosted local LLM.
- **Evidence when it matters:** Medical, veterinary, financial-market, news, weather, time, travel, and current-event queries are routed to sourced external providers.
- **No evasion:** The system prompt and routing policy are tuned to answer directly, avoid unnecessary disclaimers, and not refuse personal/family questions.
- **User-controlled learning:** Only explicit feedback (`thumbs_up/down`, corrections) is ingested into the learning pipeline; there is no implicit continuous retraining.
- **Unified entry point:** Every surface (HMI, voice, web, CLI) funnels through `tools/router_py/main.py::run(...)`.

---

## 2. System Boundary

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              Local Lucy V10                               │
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
│  │  Ollama     │  │  External   │  (Wikipedia, OpenAI, Kimi, news,     │   │
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
│   ├── Modelfile.local-lucy-michael
│   ├── Modelfile.local-lucy-racheli
│   ├── evidence_policy.yaml
│   ├── trusted_domains.yaml
│   └── url_map.yaml
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
│   ├── app/panels/control_panel.py
│   ├── app/panels/status_panel.py
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
2. **Feedback detection** — Corrections and thumbs-up/down are short-circuited to the feedback buffer / background learner.
3. **Classify & route** — `classify.classify_intent()` + `select_route()` produce a `RoutingDecision`.
4. **Resolve provider** — `provider_resolver` maps the route to a concrete provider plan.
5. **Execute** — `execution_engine` runs the plan in a sandboxed Python namespace.
6. **Generate answer** — `local_answer` streams the final response from Ollama (or formats external provider output).
7. **Persist** — Turn is written to SQLite; feedback/state files are updated.

---

## 5. Routing & Classification

Routing is **deterministic-first, semantic-second**.

### 5.1 Policy Router (`tools/router_py/policy_router.py`)

A ordered set of regex/heuristic gates runs before the embedding model. Current gates include:

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
- **Memory follow-up guard** — Explicit memory-recall phrases ("what did we discuss earlier?") override live-data routes back to `LOCAL` when session memory is enabled.
- **Short-query guard** — Utterances like "thanks", "ok", "wrong" stay `LOCAL`.
- **Hostile override** — Adversarial probes are forced `LOCAL`.

### 5.4 Route Labels

`LOCAL`, `AUGMENTED`, `EVIDENCE`, `NEWS`, `WEATHER`, `TIME`, `FINANCE`, `CLARIFY`, `MEMORY_FOLLOWUP`, `TRAVEL_TOURISM`, `HEBREW_QUERY`, `LOCAL_REASONING`, `EPHEMERAL`.

---

## 6. Provider & Evidence Layer

Providers are Python modules loaded and executed inside `execution_engine.py`. There is no shell-script dispatch.

| Route | Primary provider | Notes |
|-------|------------------|-------|
| `LOCAL` | Ollama local model | Injects session memory + persistent facts |
| `AUGMENTED` | Wikipedia → OpenAI → Kimi | Sourced external answer |
| `EVIDENCE` | Trusted evidence (Wikipedia + allowlisted domains) | Medical/vet/finance/legal safety route |
| `NEWS` | News provider | Current headlines / synthesis |
| `WEATHER` | Weather provider | Live forecast |
| `TIME` | Time API | Current time by location |
| `FINANCE` | Finance provider | Live market data with citations |

Evidence source quality is constrained by `config/trusted_domains.yaml` and `config/url_map.yaml`. Medical and veterinary queries always require trusted evidence; they cannot be overridden to a generative provider.

---

## 7. Execution Engine

`tools/router_py/execution_engine.py` (~3,700 lines) is the central dispatch layer:

- Builds a Python execution plan from the resolved route.
- Runs in an isolated namespace.
- Loads relevant memory context.
- Calls the appropriate provider function.
- Formats the response and writes structured state updates via `StateWriter`.
- On failure, escalates to clarification or local reasoning rather than crashing.

---

## 8. Local Answer & Model Selection

### 8.1 Local Answer (`tools/router_py/local_answer.py`)

- Async Ollama client with streaming support.
- Builds the final prompt from the selected Modelfile, session memory, persistent facts, and any fetched external context.
- Enforces first-person self-reference and self-knowledge boundaries through the system prompt.

### 8.2 Model Selector (`tools/router_py/model_selector.py`)

The UI exposes five selector entries:

| UI entry | Base model | Notes |
|----------|------------|-------|
| `auto` | Router-dependent | Chooses by query bucket |
| `local-lucy-llama31` | `llama3.1:8b` | Default; 8192 context; fast; literal system-prompt following |
| `qwen3` | `qwen3:14b` | Stronger reasoning; privacy guardrails on personal queries |
| `fast` | `qwen3:14b` | Same base as qwen3, optimized for low latency |
| `mistral` | `mistral-nemo` | Less constrained, drier/encyclopedic style |

Additional persona Modelfiles exist for `michael`, `racheli`, `stable`, and `mem` but are not in the main selector.

### 8.3 Default Modelfile (`config/Modelfile.local-lucy-llama31`)

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
- Do not fabricate facts. Say "I don't know" when uncertain.
- Answer directly and factually. Never apologize, hedge, or add disclaimers.
- Do not refuse questions about the user, their family, or their pets.
- Facts only. Nothing else.
"""
```

---

## 9. Memory, Feedback & Learning

### 9.1 Session Memory (`tools/memory/memory_service.py`)

- SQLite tables: `conversation_turns`, `session_summaries`, `summary_embeddings`, `archived_turns`, `session_metadata`.
- Last few turns are prepended to the prompt.
- Session summaries are embedded with MiniLM for long-context retrieval.
- Personal/family queries suppress noisy session memory when explicit persistent facts are available.

### 9.2 Persistent Memory

- SQLite table: `persistent_facts`.
- Stores approved facts (family members, pets, preferences, addresses).
- MiniLM embeddings pre-computed at storage time; semantic retrieval threshold ~0.35.

### 9.3 Feedback Buffer (`tools/router_py/feedback_buffer.py`)

- Ring buffer of recent exchanges.
- Used for fast correction replay and continuation-follow-up inheritance.

### 9.4 Background Learner (`models/router/background_learner.py`)

- Ingests **explicit user feedback only**.
- Safety gate prevents auto-learning of medical/vet/evidence routes without human review.
- Versioned examples go to `comprehensive_examples.json`; high-stakes or conflicting feedback goes to `pending_review.jsonl`.

---

## 10. Voice Subsystem

```
PTT press → record audio → whisper_worker.py (whisper.cpp) → transcript
   → router → execution engine → local_answer → tts_adapter.py (Kokoro/Piper/Edge) → audio out
```

- STT: whisper.cpp server, GPU if available.
- TTS: Kokoro by default; Piper and Edge TTS are fallback options. GPU is avoided for TTS to prevent OOM (`LUCY_VOICE_KOKORO_DEVICE=cpu`).
- Integration points: `tools/router_py/streaming_voice.py`, `tools/runtime_voice.py`.

---

## 11. UI / HMI & Web Adapter

### 11.1 Desktop UI (`ui-v10/`)

- `app/services/runtime_bridge.py` calls Python functions directly (`main.run(...)`, `execute_plan_python(...)`); no shell indirection.
- `app/panels/control_panel.py`: model selector, toggles (web, voice, evidence, memory), persona selector.
- `app/panels/status_panel.py`: runtime diagnostics and request status.

### 11.2 Runtime Control

- `START_LUCY.sh` — desktop shortcut entry point.
- `tools/runtime_control.py` / `tools/runtime_request.py` — process lifecycle and local API access.

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
| `tools/router_py/test_*.py` | Routing, policy, classification, finance, medical, news, edge cases |
| `tools/tests/` | Memory service, end-to-end comprehensive tests |
| `tools/voice/tests/` | TTS fallback, voice utilities |
| `ui-v10/tests/` | Off-screen HMI tests |
| `web_adapter/test_web_adapter.py` | HTTP adapter tests |

Run the routing/policy suite:

```bash
cd /home/mike/lucy-v10/tools/router_py
python3 -m pytest test_policy_router.py test_classify.py test_routing_edge_cases.py test_policy.py test_finance_routing.py test_medical_evidence_routing.py test_news_synthesis_routing.py test_augmented_auto_routing.py -v
```

---

## 14. What Changed Since the 2026-06-08 Architecture Doc

| Old claim | Current reality |
|-----------|-----------------|
| Routing was "MiniLM k=3 nearest-neighbor" | Fine-tuned MiniLM + classifier head with confidence thresholds |
| Default `local-lucy-llama31` context was 4096 | **8192** |
| 4-model selector | **5-model selector** (`auto`, `llama31`, `qwen3`, `fast`, `mistral`) |
| Shell-based provider / UI-bridge execution | **Python-native** execution engine and runtime bridge |
| Background learner ingested general user feedback | **Explicit feedback only**, safety-gated and versioned |
| Route list omitted newer buckets | Added `FINANCE`, `EVIDENCE`, `TRAVEL_TOURISM`, `HEBREW_QUERY`, `MEMORY_FOLLOWUP`, `CLARIFY`, `EPHEMERAL`, `LOCAL_REASONING` |
| No web adapter documented | `web_adapter/server.py` is a first-class optional surface |
| No persona Modelfiles mentioned | `michael`, `racheli`, `stable`, `mem` variants exist |

---

*End of architecture document.*
