# Local Lucy V11 — Architecture

**Date:** 2026-07-29  
**Version:** v11  
**Branch:** feature/v11-pipeline-split-escalation  
**Scope:** English-only primary runtime

> This document describes **v11 as implemented** on the `feature/v11-pipeline-split-escalation` branch. Hebrew / Racheli support has been removed from the primary runtime; the standalone Hebrew assistant was archived separately on 2026-07-10.
>
> Latest commit on `feature/v11-pipeline-split-escalation`: see `git log`.

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
- **Modular router_py:** As of 2026-07-29 the large monolithic modules in `tools/router_py/` are being split into focused packages with preserved public APIs and characterization tests.

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
lucy-v11/
├── config/                    # Modelfiles, system prompts, policy configs
│   ├── Modelfile.local-lucy-llama31
│   ├── Modelfile.local-lucy-gemma4
│   ├── capability_flags.yaml  # Conservative feature flags for v11 pipeline expansion
│   ├── evidence_policy.yaml
│   ├── trusted_domains.yaml
│   ├── url_map.yaml
│   ├── latency_optimizations.env
│   ├── architecture_prompt.txt # Short architecture brief fed to the LLM
│   ├── personas/              # Runtime prompt-level persona fragments
│   ├── modes/                 # Mode/policy configuration files
│   └── quarantined/           # Removed/disabled Modelfiles and persona variants
├── models/router/             # Fine-tuned MiniLM router, examples, learner
│   ├── hybrid_router_v2.py
│   ├── comprehensive_examples.json
│   ├── finetuned_minilm/
│   ├── background_learner.py
│   └── pending_review.jsonl
├── tools/router_py/           # Core execution engine (Python-native)
│   ├── main.py
│   ├── request_pipeline.py    # thin orchestration facade → pipeline/
│   ├── pipeline/              # classify → route → resolve → execute → outcome
│   ├── classify.py            # thin facade → classify_core/
│   ├── classify_core/         # intent, guards, memory gate, router, select
│   ├── policy.py              # thin facade → policy/
│   ├── policy/                # domain-specific guard lists
│   ├── policy_router.py       # thin facade → policy_router/
│   ├── policy_router/         # individual guard groups
│   ├── execution_engine.py    # thin facade → execution_engine/
│   ├── execution_engine/      # provider dispatch, plan execution, result assembly
│   ├── execution_engine_state.py
│   ├── local_answer.py        # thin facade → local_answer_core/
│   ├── local_answer_core/     # prompt builders, engine, self-knowledge, utils
│   ├── state_manager.py       # thin facade → state/
│   ├── state/                 # schema, queries, manager
│   ├── context_guard/         # relevance guard (split from context_guard.py)
│   ├── streaming_voice/       # streaming TTS pipeline (split from streaming_voice.py)
│   ├── feedback_parser/       # feedback parsing (split from feedback_parser.py)
│   ├── news/                  # news provider (split from news_provider.py)
│   ├── voice/                 # voice pipeline (split from voice_tool.py)
│   ├── escalation/            # escalation suggestions and critical-source guard
│   ├── planner/               # plan-to-pipeline CLI helpers
│   ├── plan_to_pipeline_cli.py# CLI facade → planner/
│   ├── model_selector.py
│   ├── self_analysis.py
│   ├── feedback_buffer.py
│   ├── providers/
│   └── core/                  # Semantic interpreter / intent classifier / policy engine
│       ├── intent_classifier.py
│       ├── semantic_interpreter.py
│       ├── policy_router.py
│       └── policy_engine.py
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
├── docs/                      # Handoffs, GPU allocation notes, reports
├── dev_notes/                 # Session handoffs
└── START_LUCY.sh              # Desktop shortcut entry point
```

### 3.1 Split packages in `tools/router_py/`

| Package | Former monolith | Responsibility |
|---|---|---|
| `pipeline/` | `request_pipeline.py` | Request pipeline stages: classify, route, resolve provider, build context, execute, build outcome |
| `planner/` | `plan_to_pipeline_cli.py` | Plan-to-pipeline CLI helpers: plan building, policy resolution, contract assembly |
| `escalation/` | new for v11 | Escalation suggestions, general-knowledge web fetch, critical-source guard |
| `classify_core/` | `classify.py` | Intent classification, guard detectors, memory gate, router lifecycle, route selection |
| `policy/` | `policy.py` | Domain-specific guard lists (medical, software, finance, news, etc.) |
| `policy_router/` | `policy_router.py` | Individual guard groups (time, weather, finance, news, medical, constraints) |
| `execution_engine/` | `execution_engine.py` | Provider dispatch, plan execution, result assembly |
| `local_answer_core/` | `local_answer.py` | Prompt builders, engine, self-knowledge, utils |
| `state/` | `state_manager.py` | Schema SQL, migration helpers, query helpers, StateManager public API |
| `context_guard/` | `context_guard.py` | Evidence/memory relevance scoring with semantic + keyword fallback |
| `streaming_voice/` | `streaming_voice.py` | Streaming TTS pipeline, Kokoro worker management, audio levels |
| `feedback_parser/` | `feedback_parser.py` | Feedback parsing, inference, logging, memory retraction, learning trigger |
| `news/` | `news_provider.py` | RSS/news aggregation providers |
| `voice/` | `voice_tool.py` | Voice processing pipeline |

Each split preserves the original import path via a thin `__init__.py` facade or a backward-compatible top-level module (`classify.py`, `state_manager.py`, etc.).

---

## 4. Request Pipeline

The request pipeline has two layers:

- **`main.run()` wrapper** handles ingest, feedback detection, and surface-level setup, then calls `request_pipeline.process()`.
- **`request_pipeline.process()`** runs the canonical 10-stage flow described in §4.1, including the Gemma 4 smart-routing bypass through `pipeline.classify.classify_question()`.

### 4.1 Pipeline Facade (`tools/router_py/request_pipeline.py`)

`request_pipeline.py` is now a thin orchestration facade. Its `process()` function delegates each stage to a focused sub-module under `tools/router_py/pipeline/`. This keeps the choke-point readable while making each stage independently testable and patchable.

The `process()` flow is:

1. **Environment bypass** — `process()` orchestrates the env bypass by calling helpers in `pipeline/classify.py` (`_forced_route_from_env`, `_bypass_classification_decision`); `LUCY_ROUTER_BYPASS` / `LUCY_CHAT_FORCE_MODE` short-circuit to a forced route.
2. **Classify** — `process()` calls `pipeline.classify.classify_question()`, which runs intent classification and the Gemma 4 smart-routing bypass. The bypass can set a `route_prefix` (e.g., `NEWS`, `EVIDENCE`) or produce a bypass `RoutingDecision` for ordinary queries.
3. **Route** — `pipeline.route.select_route_for_question()` produces a raw `RoutingDecision`.
4. **Resolve provider** — `pipeline.resolve_provider.resolve_provider()` applies route prefixes, `augmented_direct_once`, centralized provider resolution, and request-scoped constraints.
5. **Critical-source policy** — `pipeline.route.apply_critical_source_policy()` restricts critical categories to trusted sources.
6. **Evidence-disabled gate** — `pipeline.route.apply_evidence_disabled_gate()` blocks or degrades routes when evidence is disabled.
7. **Build context** — `pipeline.build_context.build_pipeline_context()` assembles the `PipelineContext`.
8. **Execute** — `pipeline.execute.execute_request()` invokes `ExecutionEngine`.
9. **Build outcome** — `pipeline.outcome.build_outcome()` converts `ExecutionResult` → `RouterOutcome` and attaches source attribution / escalation suggestions.
10. **Optional web fetch** — If `auto_web_general_knowledge` is enabled, an untrusted web fetch may be performed for thin local answers.

### 4.2 `pipeline/` Package Modules

| Module | Responsibility |
|---|---|
| `pipeline/classify.py` | Intent classification wrapper, Gemma 4 smart-routing bypass, legacy env-bypass helpers (called by `process()`), self-analysis pre-check. |
| `pipeline/route.py` | Raw route selection via `select_route()`, evidence-disabled operator gate, critical-source trusted-source policy. |
| `pipeline/resolve_provider.py` | Route normalization: prefix override, `augmented_direct_once`, provider resolution, request constraints. |
| `pipeline/build_context.py` | `PipelineContext` assembly from environment variables and caller extras. |
| `pipeline/execute.py` | `ExecutionEngine` invocation and failure-to-`ExecutionResult` conversion. |
| `pipeline/outcome.py` | `ExecutionResult` → `RouterOutcome` conversion, latency profiling metadata, source attribution / trust label / escalation suggestion assembly. |
| `pipeline/attribution.py` | `SourceAttribution` builder and trust-label mapping (gated by `source_attribution` flag). |
| `pipeline/config.py` | `CapabilityFlags` dataclass and YAML/env loading. |

### 4.3 `planner/` Package Modules

`planner/` holds the internals of `tools/router_py/plan_to_pipeline_cli.py`. The CLI is now a thin wrapper; plan construction and policy resolution live in focused modules.

| Module | Responsibility |
|---|---|
| `planner/cli.py` | Argparse handling, stage timing, JSON output, orchestration of the plan-to-pipeline flow. |
| `planner/plan_builder.py` | Legacy plan extraction, semantic-interpretation patching, route-prefix effective-plan construction. |
| `planner/policy_resolver.py` | Contextual followup resolution, local-context response matching, pet-food policy, local-response ID matching. |
| `planner/news_rewriter.py` | Conservative news-query rewriting when the router selects `NEWS`. |
| `planner/contract_builder.py` | Execution-contract assembly and full CLI output dictionary construction via the runtime governor. |

### 4.4 `escalation/` Package Modules

`escalation/` is new for v11. It provides conservative escalation suggestions and a critical-source guard, all gated by capability flags.

| Module | Responsibility |
|---|---|
| `escalation/config.py` | Critical-category list and human-readable suggestion strings. |
| `escalation/suggestion.py` | `suggest_escalation()` — returns a short web-escalation hint only when the `suggest_web_escalation` flag is on, the route is `LOCAL`, and the category is not critical. |
| `escalation/fetcher.py` | DuckDuckGo HTML fetcher for general-knowledge web results (used only when `auto_web_general_knowledge` is enabled). |
| `escalation/critical_guard.py` | `is_critical_category()`, trusted-domain allowlist resolution, and the `operator_blocked` helper used by the critical-source policy. |

### 4.5 Capability Flags (`config/capability_flags.yaml`)

The `config/capability_flags.yaml` file controls conservative v11 pipeline features. Every flag defaults to off (or to the safest setting) so the default runtime behaviour is unchanged.

| Flag | Default | Effect when enabled |
|---|---|---|
| `source_attribution` | `false` | `RouterOutcome` receives `source_attribution` and `trust_label` fields describing the provenance/confidence of the answer. |
| `suggest_web_escalation` | `false` | Thin `LOCAL` answers may include a suggestion to enable web search for more sources/current information. |
| `auto_web_general_knowledge` | `false` | After a thin local answer, the pipeline fetches one DuckDuckGo result and reports it as an untrusted web source in `escalation_suggestion`. The local answer is never replaced. |
| `trusted_sources_only_critical` | `true` | Critical categories (medical, financial, legal, safety, identity, travel advisory) are restricted to trusted-domain allowlists. Untrusted web routes are blocked or redirected to trusted evidence. |

Each flag can also be overridden via environment variables:

- `LUCY_SOURCE_ATTRIBUTION=1`
- `LUCY_SUGGEST_WEB_ESCALATION=1`
- `LUCY_AUTO_WEB_GENERAL_KNOWLEDGE=1`
- `LUCY_TRUSTED_SOURCES_ONLY_CRITICAL=1`

Set the env var to `0` to disable the corresponding feature.

### 4.6 Critical-Source Policy

The critical-source policy enforces a trusted-sources-only rule for sensitive categories. It is applied by `pipeline.route.apply_critical_source_policy()` after provider resolution and before execution.

- Critical categories include: medical, veterinary, financial/market/economic, legal, regulatory, safety, identity, and travel advisory.
- For critical queries, untrusted web routes are converted:
  - `NEWS` → `EVIDENCE` with provider `trusted`.
  - `AUGMENTED` → provider `trusted` with evidence required.
  - `EVIDENCE` → provider forced to `trusted` if it was not already.
- `LOCAL`, `CLARIFY`, `SELF_REVIEW`, and `MEMORY_RECALL` routes are unaffected.
- If no trusted-domain allowlist is configured for the category, the request returns an `operator_blocked` outcome rather than allowing untrusted sources.

Trusted-domain files are resolved from `config/trust/generated/` (e.g. `medical_runtime.txt`, `vet_runtime.txt`, `finance_runtime.txt`).

### 4.7 Public Interfaces Preserved

- `tools/router_py/request_pipeline.py::process(question, ...)` — unchanged signature.
- `tools/router_py/classify.py` — thin facade; `classify_intent()`, `select_route()`, and public helpers remain importable.
- `tools/router_py/plan_to_pipeline_cli.py` — CLI entry point and JSON output contract preserved.
- `RouterOutcome` — gained optional `source_attribution`, `trust_label`, and `escalation_suggestion` fields; all existing fields remain.
- `RoutingDecision` — unchanged.
- `ClassificationResult` — unchanged.

---

## 5. Routing & Classification

Routing is **deterministic-first, semantic-second**.

### 5.0 Gemma 4 Smart-Routing Bypass

When the HMI toggle `gemma4_smart_routing` is on and the selected model is `local-lucy-gemma4` (or any `gemma4:*` tag), `request_pipeline.process()` calls `pipeline.classify.classify_question()`, which checks for Gemma 4 smart routing and can either:

- Set a `route_prefix` for news/evidence keyword patterns (`latest news about ...`, `evidence for ...`), leaving normal route selection to run with that prefix.
- Produce a minimal `LOCAL` bypass `RoutingDecision` directly for ordinary queries, skipping the policy router, embedding router, and intent classifier.

This preserves:

- Explicit route prefixes (`news:`, `evidence:`, `augmented:`).
- Existing news/evidence pattern fast paths.
- Execution-engine guardrails (tool authorization, permissions, etc.).

The bypass is off by default; non-Gemma models always use the full router stack.

### 5.1 Policy Router (`tools/router_py/policy_router/`)

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

### 5.3 `classify.py` / `classify_core/` Guards

After the policy router / embedding router, `classify_core/` applies additional safety/context guards:

- **Continuation follow-up inheritance** — "Tell me more", "more details", "elaborate" inherit the route of the prior exchange if it was an evidence/external route.
- **Medical/veterinary follow-up guard** — Short ambiguous follow-ups ("why?", "is it safe?") after an `EVIDENCE` medical/vet answer stay on `EVIDENCE`/`AUGMENTED`.
- **Memory follow-up guard** — Explicit memory-recall phrases override live-data routes back to `LOCAL` when session memory is enabled.
- **Short-query guard** — Utterances like "thanks", "ok", "wrong" stay `LOCAL`.
- **Hostile override** — Adversarial probes are forced `LOCAL`.

### 5.4 Route Labels

`LOCAL`, `AUGMENTED`, `EVIDENCE`, `NEWS`, `WEATHER`, `TIME`, `FINANCE`, `CLARIFY`, `SELF_REVIEW`, `MEMORY_RECALL`.

---

## 6. Provider & Evidence Layer

Providers are Python modules loaded and executed inside `execution_engine/`.

| Route | Primary provider | Notes |
|-------|------------------|-------|
| `LOCAL` | Ollama local model | Injects session memory + persistent facts |
| `AUGMENTED` | Wikipedia evidence + OpenAI/Kimi synthesis | Sourced external answer; Wikipedia is evidence, OpenAI/Kimi synthesise |
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

`tools/router_py/execution_engine.py` is a thin facade for `tools/router_py/execution_engine/`, the central dispatch layer:

- **Python-native only** as of 2026-07-09: the legacy shell fallback path and the `use_python_path` toggle were removed. Callers (`ui-v10/app/services/runtime_bridge.py`, `tools/router_py/request_pipeline.py`) invoke Python directly.
- Builds a Python execution plan from the resolved route.
- Runs in an isolated namespace.
- Loads relevant memory context.
- Calls the appropriate provider function.
- Filters evidence and memory through `context_guard`.
- Formats the response and writes structured state updates via `StateWriter`.
- On failure, escalates to clarification or local reasoning rather than crashing.

The original monolith shrank from ~3,900 lines to ~2,216 lines after the shell removal, reducing surface area for dual-path bugs, and was later split into the `execution_engine/` package.

---

## 8. Local Answer & Model Selection

### 8.1 Local Answer (`tools/router_py/local_answer.py`)

Thin facade for `tools/router_py/local_answer_core/`:

- Async Ollama client with streaming support.
- Builds the final prompt from the selected Modelfile, session memory, persistent facts, and any fetched external context.
- Enforces first-person self-reference and self-knowledge boundaries through the system prompt.
- Detects thinking models (Qwen3, DeepSeek-R1, Gemma 4, etc.) and applies a token-budget multiplier so reasoning tokens do not swallow the visible response.
- Provides `get_gpu_free_vram_mb()` for HMI resource warnings.
- **Model identity mapping:** `_MODEL_IDENTITIES` maps each selectable backend alias (e.g. `local-lucy-llama31`, `gemma4:12b-it-qat`) to a human-readable `(ollama_name, params)` tuple. The self-knowledge system prompt is built from this map so identity answers always describe the model that is actually loaded.
- **Heartbeat retargeting:** The background Ollama keep-alive heartbeat and the recurring warmup thread both read the authoritative `current_state.json` model on every cycle and abort if it no longer matches their target. This prevents a stale heartbeat from re-loading a previously selected model after a user switch or profile reload.
- **Post-request warmup targets the effective model:** After a request, `runtime_bridge.py` keeps warm the model that actually answered, not the automatic selector's shadow recommendation, so the active model is not evicted.
- **Profile reload preserves model selection:** `tools/runtime_profile.py` resets only `profile` and `status`; it does not overwrite the user-selected model in `current_state.json`.
- **Context-follow-up memory preservation:** `local_answer_core/` detects obvious conversational continuations ("what about...", "how about...", etc.) and keeps the recent session memory unfiltered, with a prompt instruction telling the model to answer in context.
- **User persona injection (2026-07-17):** `config/personas/michael.txt` is loaded at runtime and injected into the local prompt for any local model (Llama, Gemma, etc.). Natural-language identity detection (e.g. "I am Michael") is wired in `tools/router_py/main.py`. The active persona is intentionally **not** injected into `SELF_REVIEW` prompts.

### 8.2 Model Selector (`tools/router_py/model_selector.py`)

The UI exposes an **Auto** default. In shadow mode, the selector automatically chooses the most appropriate local model by query bucket. Manual overrides remain available for power users. `local-lucy-gemma4` (backed by `gemma4:12b-it-qat`) is available as an optional reasoning/multimodal model with the same runtime persona injection as the Llama variant.

**Code-review specialist:** SELF_REVIEW mode is resolved by `tools/router_py/code_review_model_resolver.py`. The default configured specialist is `local-lucy-gemma4` (the same model used for general chat), with fallback chain: configured specialist model if enabled and installed → `local-lucy-gemma4` → raw `gemma4:12b-it-qat` → normally configured local model. If nothing in the chain is installed, the request returns `code_review_model_unavailable`. The SELF_REVIEW call expands the Ollama context window (`num_ctx`) to `code_review_context_target` (default 16384) so long file prompts do not truncate the generated review.

**Benchmarking:** `ui-v10/model_comparison_benchmark_v2.py` measures clean-slate cold-start and warm-run latency for every selectable mode (`auto`, `local-lucy-llama31`, `gemma4:12b-it-qat`). It unloads Ollama between modes, disables the repeat cache, and writes a JSON report plus a Markdown summary to the Desktop.

### 8.3 VRAM Management

- The HMI warns when Gemma 4 is selected on a GPU with <12 GB free VRAM.
- Local Lucy does not force GPU-only execution; Ollama/llama.cpp may offload layers to system RAM when VRAM is exhausted.
- The runtime evicts other loaded Ollama models when switching models, keeping only the active model in VRAM.

### 8.4 Default Modelfile (`config/Modelfile.local-lucy-llama31`)

```modelfile
FROM llama3.1:8b

# Context window: 8192 tokens (4x vs 14B models)
# Llama 3.1 8B uses ~8.5 GB VRAM at 4-bit; raising num_ctx to 8192 still fits
# comfortably inside the RTX 3060 12 GB VRAM budget with Whisper GPU headroom.
# Ollama auto-offloads layers to CPU/RAM if VRAM becomes tight.
# With 31 GB system RAM, full model execution in RAM is always possible.
PARAMETER num_ctx 8192

# Use all available CPU threads for generation
PARAMETER num_thread 8

# Zero temperature = maximally deterministic
# Required for factual accuracy and reproducible routing tests
PARAMETER temperature 0.0

# Tight nucleus sampling = faster, more focused generation
PARAMETER top_p 0.5

# Aggressive repeat penalty to reduce redundancy
PARAMETER repeat_penalty 1.2

SYSTEM """
[ARCHITECTURE]

You are Local Lucy, an AI assistant running locally on the user's computer via Ollama.

Key architectural facts:
- Generative LLM: The model that writes your answers is an Ollama-hosted LLM. The default fast path is qwen3:14b (~14B parameters, 2048-token context window). An optional variant uses Llama 3.1 8B with an 8192-token context window. This LLM is NOT the router.
- Embedding router: A fine-tuned sentence-transformers/all-MiniLM-L6-v2 model produces 384-dimensional sentence embeddings. Routing uses a k-NN index over 1,414 labelled examples plus a learned linear classifier head with k-NN fallback; the classifier confidence threshold is 0.60.
- Policy gates: Deterministic gates run before the embedding classifier and catch clear operational cases in this order: personal/family → medical/vet → local reasoning (opinion/speculation/conspiracy, with a current-information exception) → finance → time → weather → news → evidence requests → conflict analysis → public-figure age → recipe → current information → attachments.
- Routes: LOCAL (default, parametric knowledge), AUGMENTED (Wikipedia evidence with optional synthesis by OpenAI/Kimi), NEWS, TIME, WEATHER, FINANCE, EVIDENCE (trusted medical/veterinary sources with citations), EPHEMERAL (transient-data classifier label), CLARIFY.
- Execution fallback order for insufficient LOCAL answers: local fact/note RAG → web light RAG → augmented provider.
- Memory: SQLite session memory (optional HMI toggle), persistent facts stored in memory.db and retrieved semantically via MiniLM, and approved memory notes in memory/approved/.
- Voice: Whisper STT for speech input, Kokoro TTS (Piper fallback) for speech output.
- Safety: medical/veterinary queries route to EVIDENCE with trusted-domain citations; personal/family queries stay LOCAL and use persistent facts when available; creative-writing queries are forced LOCAL so they do not leak to live-data routes.

Capabilities: translation, coding, writing, reasoning, voice I/O, and live data via NEWS/WEATHER/TIME/FINANCE/AUGMENTED routes when the router activates them.

Limitations: your parametric knowledge has a training-data cutoff; as a 14B/8B-class model you can make mistakes on niche technical details, rare historical facts, and exact calculations; you do not browse the web independently unless a route explicitly requests live data; you do not read arbitrary files unless they are attached or stored in approved memory.

Anti-hallucination rule for specific real-world entities:
- When asked for factual details about a specific real-world place, person, organization, or event, do not invent dates, locations, founders, history, or capabilities. If the information is not in your parametric knowledge or in approved memory, say you do not have reliable data rather than guessing.

Truth-first discipline:
- For any factual claim about a real-world person, place, organization, event, or technical detail, you must be able to point to a source: approved memory, retrieved context, or high-confidence parametric knowledge.
- If using retrieved context, cite the source explicitly.
- If a claim is unsupported, omit it or say it is unknown. Do not fill gaps with plausible-sounding but unverified details.
- When no reliable source is available, say "I don't have reliable information" and, if appropriate, suggest using Augmented mode.
"""
```

> Note: The system prompt embedded in this Modelfile states the router uses 1,414 labelled examples. As of this writing the actual `models/router/comprehensive_examples.json` contains 1,374 examples.

### 8.5 Code-Review Specialist & `SELF_REVIEW` Route

The Engineering panel enables a read-only code-review mode for analyzing Local Lucy's own Python source. This is **not** a general chat route; it is a separate `SELF_REVIEW` execution path.

**Controls**
- HMI toggle: **Engineering mode** (relabelled from "Self-analysis mode" on 2026-07-16; stored as `self_analysis_mode` in `current_state.json`).
- Runtime env override: `LUCY_SELF_ANALYSIS_MODE=1`.
- Trigger phrase in the UI: `review your own code <relative-path.py>`; explicit `.py` file references and directory paths (e.g. `review tools/router_py`) are also detected.

**Model resolution (`tools/router_py/code_review_model_resolver.py`)**
- Configured specialist alias: `local-lucy-gemma4` (the same model used for general chat).
- Fallback chain: configured specialist alias (if enabled and installed) → `local-lucy-gemma4` → raw `gemma4:12b-it-qat` → normally configured local model.
- `LUCY_CODE_REVIEW_MODEL` overrides the specialist alias; `LUCY_CODE_REVIEW_SPECIALIST_ENABLED=0` disables the specialist search and uses the stock fallback chain.
- If no model in the chain is installed, the request returns `code_review_model_unavailable`.

**Execution (`tools/router_py/self_analysis.py`)**
- Static analysis uses `ast` plus `ruff` diagnostics.
- File references resolve to a single `.py` file; directory references are accepted and handled pragmatically:
  - Small directories (≤5 Python files) are reviewed file-by-file.
  - Large directories return a file listing and ask for a specific file, avoiding unbounded context growth.
- Two-call staged review:
  1. **Broad audit** — code map, coverage ledger, candidate findings.
  2. **Deep investigation** — runs only when stage 1 reports confirmed/high/moderate-confidence findings; traces call paths, validates defects, ranks fixes.
- Source is truncated to `LUCY_SELF_REVIEW_CONTEXT_CHARS` (default 32,768) when it exceeds the code-review context budget; the prompt is flagged with a truncation warning.
- The Ollama context window (`num_ctx`) is expanded to `LUCY_CODE_REVIEW_CONTEXT_TARGET` (default 16,384) for each SELF_REVIEW call, leaving room for the prompt, source, and the full output budget.

**HMI behaviour**
- Self-review reports are intentionally read-only and can be lengthy, so TTS is suppressed for `SELF_REVIEW` results.
- The conversation panel labels the result "Self-review answer".

### 8.6 Voice Mode & CUDA Orchestration

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

## 9. Context Guard (`tools/router_py/context_guard/`)

Every retrieved evidence item and memory turn is scored before being injected into the prompt:

- **Provenance:** Wikipedia, medical, finance, weather, and news sources score higher; generated text and memory are damped.
- **Temporal:** Current-fact queries penalise evidence older than 30 days (weather and time sources are exempt).
- **Entity collision:** A named entity in the query that does not appear in the evidence reduces the score.
- **Answerability:** Evidence with no content-word overlap with the question is heavily discounted.

If relevance is below threshold, the evidence/turn is dropped.

The package is split into:
- `config.py` — thresholds, model names, penalty constants
- `text.py` — keyword/entity extraction helpers
- `evidence.py` — evidence relevance scoring
- `memory.py` — memory turn relevance filtering

---

## 10. State (`tools/router_py/state/`)

SQLite-backed state management:

- `schema.py` — schema SQL and migration helpers
- `queries.py` — low-level query helpers (namespaces, routes, outcomes, telemetry, locks)
- `manager.py` — public `StateManager` class
- `__init__.py` — public exports

A backward-compatible facade remains at `tools/router_py/state_manager.py` so existing imports continue to work.

---

## 11. Streaming Voice (`tools/router_py/streaming_voice/`)

Streams TTS audio chunks as text is generated, eliminating delays. Manages Kokoro TTS worker as a subprocess for optimal performance.

- `pipeline.py` — `StreamingVoicePipeline` and orchestration
- `worker.py` — `KokoroWorkerManager` and Kokoro availability helpers
- `levels.py` — VU meter / audio level helpers
- `text.py` — TTS text cleaning and HTML stripping
- `__init__.py` — public facade
- `__main__.py` — CLI entry point

---

## 12. Memory, Feedback & Learning

### 12.1 Session Memory (`tools/memory/memory_service.py`)

- SQLite tables: `conversation_turns`, `session_summaries`, `summary_embeddings`, `archived_turns`, `session_metadata`.
- Last few turns are prepended to the prompt.
- Session summaries are embedded with MiniLM for long-context retrieval.
- Personal/family queries suppress noisy session memory when explicit persistent facts are available.

### 12.2 Persistent Memory

- SQLite table: `persistent_facts`.
- Stores approved facts (family members, pets, preferences, addresses).
- MiniLM embeddings pre-computed at storage time; semantic retrieval threshold ~0.35.

### 12.3 Feedback Buffer (`tools/router_py/feedback_buffer.py`)

- Ring buffer of recent exchanges.
- Used for fast correction replay and continuation-follow-up inheritance.

### 12.4 Background Learner (`models/router/background_learner.py`)

- Ingests **explicit user feedback only**.
- Safety gate prevents auto-learning of medical/vet/evidence routes without human review.
- Versioned examples go to `comprehensive_examples.json`; high-stakes or conflicting feedback goes to `pending_review.jsonl`.

---

## 13. UI / HMI & Web Adapter

### 13.1 Desktop UI (`ui-v10/`)

The HMI has been simplified to two views:

- **Default view:** Conversation history, input, memory/voice toggles, and the Auto model selector.
- **Engineering panel:** Exposes route diagnostics, provider selectors, augmentation policy, learner controls, and structured logs.

`app/services/runtime_bridge.py` calls Python functions directly (`main.run(...)`, `execute_plan_python(...)`); no shell indirection.

The control panel blocks checkbox signals while programmatically refreshing a toggle's checked state (e.g. `gemma4_smart_routing`), preventing a state-change signal from looping back into the backend action handler.

### 13.2 Runtime Control

- `START_LUCY.sh` — desktop shortcut entry point.
- `tools/runtime_control.py` / `tools/runtime_request.py` — process lifecycle and local API access.
- `config/latency_optimizations.env` — caching, timeout, and GPU knobs.

### 13.3 Web Adapter (`web_adapter/server.py`)

- Optional aioHTTP server, stateless.
- Gated by `LUCY_WEB_ENABLED=1`.
- Default bind: `127.0.0.1:8765`; supports LAN/Tailscale binding with token auth.
- REST endpoints; covered by `web_adapter/test_web_adapter.py`.

---

## 14. Configuration Reference

| File / Variable | Purpose |
|-----------------|---------|
| `.env.example` | API keys, feature flags, endpoints |
| `config/capability_flags.yaml` | Conservative v11 feature flags (source attribution, escalation, critical-source guard) |
| `config/evidence_policy.yaml` | When external evidence is allowed/required |
| `config/conversation_profile.json` | Default persona / tone |
| `config/trusted_domains.yaml` | Allowlisted evidence sources |
| `config/url_map.yaml` | Source-specific URL overrides |
| `config/latency_optimizations.env` | Caching, timeout, GPU knobs |
| `LUCY_SESSION_MEMORY=1` | Enable session memory |
| `LUCY_ENABLE_INTERNET=1` | Enable external providers |
| `LUCY_WEB_ENABLED=1` | Enable HTTP adapter |
| `LUCY_SOURCE_ATTRIBUTION=1` | Enable `source_attribution` capability flag |
| `LUCY_SUGGEST_WEB_ESCALATION=1` | Enable `suggest_web_escalation` capability flag |
| `LUCY_AUTO_WEB_GENERAL_KNOWLEDGE=1` | Enable `auto_web_general_knowledge` capability flag |
| `LUCY_TRUSTED_SOURCES_ONLY_CRITICAL=1` | Enable critical-source trusted-sources-only policy |
| `OLLAMA_FLASH_ATTENTION=1` | GPU optimization |
| `OLLAMA_KV_CACHE_TYPE=q8_0` | GPU optimization |

---

## 15. Test Structure

| Location | Coverage |
|----------|----------|
| `tests/` | Golden responses, regression cases, specific entity fact gate |
| `tools/router_py/test_*.py` | Routing, policy, classification, finance, medical, news, edge cases, evidence provider, self-analysis, code-review resolver, split characterization tests, pipeline/escalation flag tests, critical-source guard tests, source-attribution tests, web-fetcher tests |
| `tools/tests/` | Memory service, end-to-end comprehensive tests |
| `tools/voice/tests/` | TTS fallback, voice utilities |
| `ui-v10/tests/` | Off-screen HMI tests |
| `web_adapter/test_web_adapter.py` | HTTP adapter tests |

Run the fast routing/policy suite:

```bash
cd /home/mike/lucy-v11
bash scripts/run-fast-tests.sh
```

---

## 16. Module Splitting Status (as of 2026-07-29)

### Completed splits

| Original file | New package / facade | Status |
|---|---|---|
| `state_manager.py` | `state/` + `state_manager.py` facade | Merged to main |
| `news_provider.py` | `news/` | Merged to main |
| `voice_tool.py` | `voice/` | Merged to main |
| `policy.py` | `policy/` | Merged to main |
| `policy_router.py` | `policy_router/` | Merged to main |
| `execution_engine.py` | `execution_engine/` | Merged to main |
| `local_answer.py` | `local_answer_core/` + `local_answer.py` facade | Merged to main |
| `classify.py` | `classify_core/` + `classify.py` facade | Merged to main |
| `feedback_parser.py` | `feedback_parser/` | Merged to main |
| `context_guard.py` | `context_guard/` | Merged to main (post-reboot recovery) |
| `streaming_voice.py` | `streaming_voice/` | Merged to main |
| `request_pipeline.py` | `pipeline/` + `request_pipeline.py` facade | Pipeline split on `feature/v11-pipeline-split-escalation` |
| `plan_to_pipeline_cli.py` | `planner/` + `plan_to_pipeline_cli.py` facade | Planner split on `feature/v11-pipeline-split-escalation` |
| *(new)* | `escalation/` | New package for source attribution, escalation suggestions, critical-source guard on `feature/v11-pipeline-split-escalation` |

### Remaining large production files

| File | Lines | Notes |
|---|---|---|
| `main.py` | ~740 | Central orchestrator — high blast radius |
| `execution_engine_state.py` | ~666 | State persistence layer |
| `voice_recorder.py` | ~528 | Good next candidate |
| `self_analysis.py` | ~496 | Self-contained |
| `model_selector.py` | ~477 | Self-contained |

### Splitting workflow

1. Add characterization tests against the monolith.
2. Create the focused package.
3. Move code, preserving public API via facade `__init__.py`.
4. Run `bash scripts/run-fast-tests.sh`.
5. Fix regressions, commit, review.

---

## 17. What Changed for V11

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
| Monolithic `tools/router_py/` modules | **Ongoing split into focused packages** with preserved public APIs |
| Inline request-pipeline logic | **`request_pipeline.py`** is now a thin facade over `pipeline/` sub-modules |
| Inline plan-to-pipeline CLI logic | **`plan_to_pipeline_cli.py`** is now a thin facade over `planner/` sub-modules |
| No source attribution on answers | **`SourceAttribution`** added to `RouterOutcome` behind `source_attribution` flag |
| No escalation hints | **Conservative escalation suggestions** behind `suggest_web_escalation` flag |
| No automatic web fetch for general knowledge | **`auto_web_general_knowledge`** fetches one untrusted web result for thin local answers |
| Critical categories could use untrusted web sources | **Critical-source policy** restricts medical/financial/legal/safety/identity queries to trusted-domain allowlists |

---

## 18. Self-Analysis / Engineering Mode

When enabled via the **Engineering mode** toggle (relabelled from "Self-analysis mode" on 2026-07-16), Local Lucy can parse her own Python source and suggest improvements.

- The route is `SELF_REVIEW`, not `LOCAL` or `AUGMENTED`.
- Dispatch bypasses the normal routing/local-answer pipeline: `tools/router_py/execution_engine.py` detects the enabled toggle plus a `.py` file reference or directory path, resolves a code-review model (`tools/router_py/code_review_model_resolver.py`), and calls `tools/router_py/self_analysis.py::SelfAnalysisEngine` directly.
- `SelfAnalysisEngine` runs static analysis with stdlib `ast` and `ruff`, then performs a staged two-call LLM review through `LocalAnswer` with `route_mode="SELF_REVIEW"`.
- Directory references are supported: small directories (≤5 Python files) are reviewed file-by-file; large directories return a file listing so the user can pick a specific file.
- The SELF_REVIEW call expands the Ollama context window to `LUCY_CODE_REVIEW_CONTEXT_TARGET` (default 16,384) and truncates source to `LUCY_SELF_REVIEW_CONTEXT_CHARS` (default 32,768) to prevent output truncation.
- Static facts are labeled **LOCAL**; LLM suggestions are labeled **AUGMENTED**.
- The toggle is stored in `current_state.json` under `self_analysis_mode`.

---

*End of architecture document.*
