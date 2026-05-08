# Local Lucy V8 — Complete System Architecture

**Generated:** 2026-05-08  
**Version:** opt-experimental-v8-dev  
**Hardware:** RTX 3060 12GB, 31GB RAM, CPU+GPU hybrid  
**Test Suite:** 161 passed, 19 skipped, 0 failed  
**Philosophy:** *Correct answer > locality. The end justifies the means.*

---

## Mermaid: High-Level System Diagram

```mermaid
graph TB
    subgraph "User Interfaces"
        CLI["🖥️ CLI Terminal<br/>lucy_chat.sh"]
        GUI["🖼️ Qt HMI (PySide6)<br/>ui-v8/"]
        VOICE["🎤 Voice Mode<br/>PTT + STT + TTS"]
    end

    subgraph "Orchestration Layer"
        CORE["⚙️ Lucy Core<br/>runtime/lucy_core.py"]
        ENGINE["🔧 Execution Engine<br/>tools/router_py/execution_engine.py"]
        BRIDGE["🔗 Consolidated Bridge<br/>ui-v8/app/services/runtime_bridge_consolidated.py"]
    end

    subgraph "Router (Single-Path + Auto-Feedback)"
        EMBED["🧠 Embedding Router<br/>ModernBERT k-NN (PRIMARY)"]
        LEGACY["📋 Legacy Router<br/>Keyword-based (ROLLBACK ONLY)"]
        AUTO_FB["🔄 Auto-Feedback<br/>Answer Quality Analysis"]
        LEARNER["📈 Background Learner<br/>Rebuilds index from feedback"]
    end

    subgraph "AI Models"
        LLM["🤖 Qwen3 14B<br/>local-lucy (~9.8GB)"]
        ROUTER_MODEL["📊 ModernBERT-base<br/>768d embeddings"]
        WHISPER["👂 Whisper large-v3-turbo<br/>CPU:18181"]
        KOKORO["🗣️ Kokoro TTS<br/>CPU"]
    end

    subgraph "Knowledge & State"
        STATE["💾 Runtime State<br/>state/lucy_state.db + .json"]
        MEMORY["🧠 Memory Layer<br/>memory/index.jsonl"]
        HISTORY["📜 Request History<br/>state/request_history.jsonl"]
    end

    subgraph "External APIs"
        OLLAMA["🔌 Ollama API<br/>localhost:11434"]
        WIKI["📚 Wikipedia"]
        OPENAI["☁️ OpenAI / Kimi<br/>(augmented mode)"]
        NEWS["📰 RSS News Feeds"]
        TIMEAPI["⏰ TimeAPI.io"]
        SEARCH["🔍 SearXNG<br/>localhost:8080"]
    end

    CLI --> CORE
    GUI --> BRIDGE
    VOICE --> CORE

    BRIDGE --> CORE
    CORE --> ENGINE
    CORE --> STATE
    CORE --> MEMORY
    CORE --> HISTORY

    ENGINE --> EMBED
    EMBED -.->|"LUCY_ROUTER_LEGACY_PRIMARY=1"| LEGACY
    ENGINE -.->|"post-execution"| AUTO_FB
    AUTO_FB -.->|"auto_feedback.jsonl"| LEARNER
    LEARNER -.->|"rebuild"| EMBED

    ENGINE --> LLM
    ENGINE --> ROUTER_MODEL

    LLM --> OLLAMA

    EMBED -->|"LOCAL"| LLM
    EMBED -->|"AUGMENTED"| OPENAI
    EMBED -->|"NEWS"| NEWS
    EMBED -->|"TIME"| TIMEAPI
    EMBED -->|"fallback"| WIKI

    VOICE --> WHISPER
    VOICE --> KOKORO

    OPENAI --> SEARCH
    WIKI --> SEARCH
```

---

## ASCII: Component-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                    USER INTERFACES                                       │
│  ┌──────────────┐  ┌──────────────────────────────┐  ┌────────────────────────────────┐ │
│  │  CLI Shell   │  │     Qt HMI (PySide6)         │  │       Voice Mode (PTT)         │ │
│  │ lucy_chat.sh │  │  ui-v8/app/ui/main_window.py │  │  Press-to-Talk + STT + TTS     │ │
│  └──────┬───────┘  └──────────────┬───────────────┘  └───────────────┬────────────────┘ │
└─────────┼─────────────────────────┼────────────────────────────────────┼──────────────────┘
          │                         │                                    │
          │    ┌────────────────────┴────────────────────────────────────┘
          │    │
          ▼    ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                   ORCHESTRATION LAYER                                    │
│                                                                                          │
│  ┌─────────────────────────────────────────────────────────────────────────────────────┐ │
│  │                         CONSOLIDATED HMI BRIDGE                                      │ │
│  │   ui-v8/app/services/runtime_bridge_consolidated.py                                   │ │
│  │   • Atomic state writes (fcntl + tempfile + os.replace)                              │ │
│  │   • Voice PTT state machine                                                          │ │
│  │   • Model selector / augmented controls                                              │ │
│  │   • Status panel counters                                                            │ │
│  └────────────────────────────────┬────────────────────────────────────────────────────┘ │
│                                   │                                                      │
│                                   ▼                                                      │
│  ┌─────────────────────────────────────────────────────────────────────────────────────┐ │
│  │                              LUCY CORE ENGINE                                        │ │
│  │                         runtime/lucy_core.py                                          │ │
│  │   • Query ingestion & sanitization                                                   │ │
│  │   • Route dispatch (embedding primary / legacy rollback)                             │ │
│  │   • Response streaming & formatting                                                  │ │
│  │   • Token budget enforcement (chat:256, brief:128, detail:768, augmented:128)       │ │
│  └────────────────────────────────┬────────────────────────────────────────────────────┘ │
│                                   │                                                      │
│                                   ▼                                                      │
│  ┌─────────────────────────────────────────────────────────────────────────────────────┐ │
│  │                           EXECUTION ENGINE                                           │ │
│  │                      tools/router_py/execution_engine.py                              │ │
│  │   • Tool discovery & loading                                                         │ │
│  │   • Python/shell execution path selection                                            │ │
│  │   • Concurrency management                                                           │ │
│  │   • Result caching                                                                   │ │
│  │   • Auto-feedback: answer quality analysis post-execution                            │ │
│  └────────────────────────────────┬────────────────────────────────────────────────────┘ │
└───────────────────────────────────┼──────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                         ROUTER LAYER (Single-Path + Auto-Feedback)                       │
│                                                                                          │
│   ┌─────────────────────────────────────────────────────────────────────────────────┐   │
│   │  EMBEDDING ROUTER (PRIMARY)                                                      │   │
│   │  models/router/hybrid_router.py  +  tools/router_py/classify.py                  │   │
│   │                                                                                  │   │
│   │  Stage 0: Creative Guard    Stage 1: Keyword Evidence    Stage 2: Embedding k-NN │   │
│   │  ┌──────────────┐           ┌──────────────┐            ┌──────────────┐         │   │
│   │  │ Write+Story  │           │ Medical      │            │ ModernBERT   │         │   │
│   │  │ → LOCAL      │           │ Financial    │───────────▶│ [CLS] token  │         │   │
│   │  │              │           │ Legal        │            │ + cosine sim │         │   │
│   │  └──────────────┘           │ Cooking→LOCAL│            │ k=3 neighbors│         │   │
│   │                             └──────────────┘            └──────────────┘         │   │
│   │                                                                                  │   │
│   │  Stage 3: Override Rules                                                         │   │
│   │  • Time → TIME    • News → NEWS    • Evidence → AUGMENTED                        │   │
│   │                                                                                  │   │
│   │  Dataset: 346 examples (static + learned)                                        │   │
│   │  Test accuracy: 74/74 (100%) adversarial suite                                   │   │
│   │  Inference: 30–80ms/query on CPU                                                 │   │
│   └────────────────────────────────────────┬─────────────────────────────────────────┘   │
│                                            │                                             │
│   ┌────────────────────────────────────────┴─────────────────────────────────────────┐   │
│   │  LEGACY ROUTER (ROLLBACK ONLY)                                                   │   │
│   │  tools/router_py/classify.py::_select_route_legacy()                             │   │
│   │                                                                                  │   │
│   │  • Env: LUCY_ROUTER_LEGACY_PRIMARY=1                                             │   │
│   │  • Keyword-based evidence + intent mapping                                       │   │
│   │  • Preserved for emergency rollback                                              │   │
│   │  • Legacy audit computed on every call (~1μs) but never returned                 │   │
│   └────────────────────────────────────────┬─────────────────────────────────────────┘   │
│                                            │                                             │
│   ┌────────────────────────────────────────┴─────────────────────────────────────────┐   │
│   │  AUTO-FEEDBACK (NEW)                                                             │   │
│   │  models/router/auto_feedback.py                                                  │   │
│   │                                                                                  │   │
│   │  Trigger: ExecutionEngine detects poor answer quality                            │   │
│   │  Heuristics:                                                                     │   │
│   │    • AUGMENTED provider error / "I don't know" / empty → suggest LOCAL           │   │
│   │    • LOCAL medical/financial/legal disclaimer → suggest AUGMENTED                │   │
│   │    • LOCAL "I don't know" on factual query → suggest AUGMENTED                   │   │
│   │  Output: models/router/auto_feedback.jsonl                                       │   │
│   └────────────────────────────────────────┬─────────────────────────────────────────┘   │
│                                            │                                             │
│   ┌────────────────────────────────────────┴─────────────────────────────────────────┐   │
│   │  BACKGROUND LEARNER                                                              │   │
│   │  models/router/background_learner.py                                             │   │
│   │                                                                                  │   │
│   │  Input: auto_feedback.jsonl  ──▶  Process  ──▶  Add to index                    │   │
│   │  Input: user_feedback.jsonl  ──▶  Process  ──▶  Rebuild embeddings              │   │
│   │  Input: router_decisions.jsonl ──▶  Process  ──▶  Deduplicate                   │   │
│   │                                                                                  │   │
│   │  Run: python background_learner.py --process                                     │   │
│   │  Daemon: python background_learner.py --daemon --interval 60                     │   │
│   └──────────────────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                    AI MODELS LAYER                                       │
│                                                                                          │
│  ┌─────────────────────────┐  ┌─────────────────────────┐  ┌─────────────────────────┐  │
│  │     Qwen3 14B           │  │   ModernBERT-base       │  │  Whisper large-v3-turbo │  │
│  │     local-lucy          │  │   768d embeddings       │  │  STT Server (CPU)       │  │
│  │     ~9.8GB VRAM         │  │   Router classifier     │  │  Port 18181             │  │
│  │     Flash Attention     │  │   ~149M params          │  │  Auto GPU→CPU fallback  │  │
│  │     Context: 2048       │  │   Zero training needed  │  │  Orphan process kill    │  │
│  └───────────┬─────────────┘  └───────────┬─────────────┘  └───────────┬─────────────┘  │
│              │                            │                            │              │
│  ┌───────────┴─────────────┐  ┌───────────┴─────────────┐  ┌───────────┴─────────────┐  │
│  │     Kimi / OpenAI       │  │  Trained Model (V2)     │  │     Kokoro TTS          │  │
│  │     Augmented mode      │  │  NOT DEPLOYED           │  │     CPU-based           │  │
│  │     Fallback provider   │  │  92% synthetic acc      │  │     Socket→finally      │  │
│  │     Evidence mode       │  │  0% real query acc      │  │     Temp file cleanup   │  │
│  └─────────────────────────┘  └─────────────────────────┘  └─────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                              KNOWLEDGE & STATE LAYER                                     │
│                                                                                          │
│  ┌─────────────────────────┐  ┌─────────────────────────┐  ┌─────────────────────────┐  │
│  │   Runtime State         │  │   Memory Layer          │  │   Request History       │  │
│  │   state/lucy_state.db   │  │   memory/index.jsonl    │  │   state/request_        │  │
│  │   SQLite: 1302 routes   │  │   Propose/Approve       │  │   history.jsonl         │  │
│  │   Atomic writes (lock)  │  │   lifecycle             │  │   144 entries           │  │
│  │   Schema version aware  │  │   persistence           │  │   Query/response pairs  │  │
│  └─────────────────────────┘  └─────────────────────────┘  └─────────────────────────┘  │
│                                                                                          │
│  ┌─────────────────────────┐  ┌─────────────────────────┐  ┌─────────────────────────┐  │
│  │   Voice Runtime         │  │   State Archives        │  │   Router Audit          │  │
│  │   voice_runtime.json    │  │   state_ARCHIVE_*       │  │   logs/router/          │  │
│  │   Schema v2 (migrated)  │  │   Historical backups    │  │   router_decisions.jsonl│  │
│  │   PTT state machine     │  │                         │  │   Full diagnostics      │  │
│  └─────────────────────────┘  └─────────────────────────┘  └─────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                              EXTERNAL SERVICES LAYER                                     │
│                                                                                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │
│  │   Ollama    │  │  Wikipedia  │  │  SearXNG    │  │   News RSS  │  │  TimeAPI.io │  │
│  │  :11434     │  │  (free)     │  │  :8080      │  │  Feeds      │  │  (free)     │  │
│  │  Local LLM  │  │  Background │  │  Web search │  │  Current    │  │  Real-time  │  │
│  │  serving    │  │  knowledge  │  │  aggregator │  │  events     │  │  time data  │  │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘  │
│                                                                                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                                    │
│  │   OpenAI    │  │    Kimi     │  │   Grok      │                                    │
│  │  (paid)     │  │  (paid)     │  │  (paid)     │                                    │
│  │  GPT-4      │  │  Moonshot   │  │  xAI        │                                    │
│  │  Augmented  │  │  Augmented  │  │  Augmented  │                                    │
│  └─────────────┘  └─────────────┘  └─────────────┘                                    │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Data Flow: Query Lifecycle

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              QUERY LIFECYCLE                                     │
└─────────────────────────────────────────────────────────────────────────────────┘

User Query
    │
    ▼
┌─────────────────────────┐
│ 1. INGESTION            │  ← Sanitize, normalize, detect language
│    lucy_core.py         │
└──────────┬──────────────┘
           │
           ▼
┌─────────────────────────┐
│ 2. ROUTING              │
│    classify.py          │
│                         │
│  ┌───────────────────┐  │
│  │ Embedding Router  │  │  ← PRIMARY: ModernBERT k-NN + guards
│  │ (Single-path)     │  │     Returns route + provider + diagnostics
│  └─────────┬─────────┘  │
│            │            │
│  ┌─────────┴─────────┐  │
│  │ Legacy Audit      │  │  ← Always computed, logged, never returned
│  │ (~1μs)            │  │     For rollback validation only
│  └───────────────────┘  │
└──────────┬──────────────┘
           │
           ▼
┌─────────────────────────┐
│ 3. EXECUTION            │
│    execution_engine.py  │
│                         │
│  LOCAL  ──▶  qwen3 14B  │  ← Direct local inference
│  NEWS   ──▶  RSS feeds   │  ← Fetch + summarize
│  TIME   ──▶  TimeAPI.io  │  ← Current time data
│  AUG    ──▶  OpenAI/Kimi │  ← Web search + LLM synthesis
│         or Wikipedia     │  ← Free knowledge source
└──────────┬──────────────┘
           │
           ▼
┌─────────────────────────┐
│ 4. RESPONSE             │
│    Streaming output     │  ← Token-by-token to UI
│    + TTS (if voice)     │  ← Kokoro text-to-speech
│    + History append     │  ← Locked write to JSONL
└──────────┬──────────────┘
           │
           ▼
┌─────────────────────────┐
│ 5. AUTO-FEEDBACK        │  ← ExecutionEngine analyzes answer quality
│    auto_feedback.py     │    Detects misroutes heuristically
│                         │    Writes auto_feedback.jsonl
└──────────┬──────────────┘
           │
           ▼
┌─────────────────────────┐
│ 6. BACKGROUND LEARNING  │  ← background_learner.py --process
│                         │    Ingests auto-feedback + user feedback + logs
│                         │    Rebuilds embedding index
└─────────────────────────┘
```

---

## Mermaid: Router Detail View

```mermaid
flowchart TD
    subgraph "Router Decision Flow"
        direction TB
        Q["User Query"] --> EMPTY{"Empty?"}
        EMPTY -->|yes| LOC["LOCAL<br/>confidence=1.0"]
        EMPTY -->|no| CREATIVE{"Creative?"}

        CREATIVE -->|write+story/poem| LOC
        CREATIVE -->|no| EVID{"Evidence Required?"}

        EVID -->|Medical/Financial/Legal| AUG["AUGMENTED<br/>prefer_paid=True<br/>Provider: OpenAI"]
        EVID -->|No evidence| EMBED["Embedding k-NN<br/>k=3 neighbors"]

        EMBED -->|top match| PRED["Predicted Route"]
        PRED --> OVERRIDE{"Override?"}

        OVERRIDE -->|time→TIME| TIME["TIME<br/>TimeAPI.io"]
        OVERRIDE -->|news→NEWS| NEWS["NEWS<br/>RSS Provider"]
        OVERRIDE -->|evidence→AUG| AUG2["AUGMENTED<br/>prefer_paid=False"]
        OVERRIDE -->|none| FINAL["Final Route"]

        FINAL -->|LOCAL| LOC2["LOCAL<br/>qwen3 14B"]
        FINAL -->|AUGMENTED| AUG3["AUGMENTED<br/>OpenAI/Kimi"]
    end

    subgraph "Auto-Feedback Loop"
        direction TB
        EXEC["Execute Route"] --> ANS["Answer Quality Check"]
        ANS -->|AUG failed| FB1["Suggest LOCAL<br/>auto_feedback.jsonl"]
        ANS -->|LOCAL disclaimer| FB2["Suggest AUGMENTED<br/>auto_feedback.jsonl"]
        ANS -->|LOCAL ignorance| FB3["Suggest AUGMENTED<br/>auto_feedback.jsonl"]
        ANS -->|OK| NO["No action"]
        FB1 --> LEARN["Background Learner<br/>--process"]
        FB2 --> LEARN
        FB3 --> LEARN
        LEARN --> IDX["Rebuild Index<br/>comprehensive_index.jsonl"]
    end
```

---

## Mermaid: State & Persistence Flow

```mermaid
sequenceDiagram
    participant User
    participant HMI as Qt HMI (ui-v8)
    participant Bridge as Consolidated Bridge
    participant Core as Lucy Core
    participant Router as Embedding Router
    participant LLM as Qwen3 14B
    participant State as State Files
    participant AutoFB as Auto-Feedback

    User->>HMI: Type query / PTT
    HMI->>Bridge: Action: process_query
    Bridge->>Bridge: fcntl.flock(LOCK_EX)
    Bridge->>State: Atomic read current_state.json
    Bridge->>Bridge: Update state field
    Bridge->>State: tempfile + os.replace()
    Bridge->>Bridge: fcntl.flock(LOCK_UN)
    Bridge->>Core: Execute query
    Core->>Router: select_route(classification, policy, query)
    Router-->>Core: Route decision + diagnostics
    alt Route == LOCAL
        Core->>LLM: generate(query)
        LLM-->>Core: Response tokens
    else Route == AUGMENTED
        Core->>LLM: generate(query + context)
        LLM-->>Core: Response tokens
    else Route == NEWS
        Core->>Core: Fetch RSS + summarize
    else Route == TIME
        Core->>Core: TimeAPI.io call
    end
    Core->>AutoFB: analyze_answer_quality()
    AutoFB->>State: Append auto_feedback.jsonl
    Core->>State: Append history (locked)
    Core-->>Bridge: Response stream
    Bridge-->>HMI: Display response
    HMI-->>User: Show answer
```

---

## Component Matrix

| Component | File | Purpose | Status |
|-----------|------|---------|--------|
| **Core Engine** | `runtime/lucy_core.py` | Query ingestion, dispatch, response streaming | Stable |
| **Execution Engine** | `tools/router_py/execution_engine.py` | Tool loading, execution paths, auto-feedback | **Enhanced** |
| **Embedding Router** | `models/router/hybrid_router.py` + `tools/router_py/classify.py` | ModernBERT k-NN primary routing | **PRIMARY** |
| **Policy Engine** | `tools/router_py/policy.py` | Evidence detection, provider selection | Expanded |
| **Auto-Feedback** | `models/router/auto_feedback.py` | Answer quality misroute detection | **NEW** |
| **Background Learner** | `models/router/background_learner.py` | Index rebuild from feedback | **Active** |
| **Consolidated Bridge** | `ui-v8/app/services/runtime_bridge_consolidated.py` | HMI ↔ Core communication | Fixed |
| **Voice Runtime** | `tools/runtime_voice.py` | PTT, TTS, STT state management | Fixed |
| **Whisper Worker** | `tools/voice/whisper_worker.py` | STT server management | Fixed |
| **Kokoro Backend** | `tools/voice/kokoro_backend.py` | TTS synthesis | Fixed |
| **State Manager** | `tools/runtime_control.py` | File locking, atomic writes | Fixed |
| **History Writer** | `tools/history_logger.py` | Locked history appends | Fixed |

---

## File Locations

```
/home/mike/lucy-v8/
├── runtime/
│   └── lucy_core.py                    # Main orchestration
│
├── tools/
│   ├── router_py/
│   │   ├── classify.py                 # Single-path router (embedding primary, legacy rollback)
│   │   ├── policy.py                   # Evidence keywords
│   │   ├── execution_engine.py         # Tool execution + auto-feedback hooks
│   │   ├── local_answer.py             # Local LLM path
│   │   └── request_tool.py             # API requests
│   │
│   ├── voice/
│   │   ├── whisper_worker.py           # STT management
│   │   ├── kokoro_backend.py           # TTS synthesis
│   │   └── streaming_voice.py          # Voice streaming
│   │
│   ├── runtime_voice.py                # Voice state
│   ├── runtime_control.py              # State management
│   └── chat/
│       └── lucy_chat_tools.py          # Chat utilities
│
├── models/
│   └── router/
│       ├── hybrid_router.py            # Embedding k-NN + guards
│       ├── background_learner.py       # Continuous learning from feedback
│       ├── auto_feedback.py            # Answer quality analysis (NEW)
│       ├── embedding_router.py         # Base k-NN
│       ├── comprehensive_index.jsonl   # 346 examples
│       ├── comprehensive_embeddings.npy# ModernBERT vectors
│       └── checkpoints/              # Trained model (not deployed)
│
├── ui-v8/
│   └── app/
│       ├── ui/
│       │   └── main_window.py          # Qt HMI
│       └── services/
│           └── runtime_bridge_consolidated.py  # HMI bridge
│
├── state/
│   ├── lucy_state.db                   # SQLite routes (1302)
│   ├── request_history.jsonl           # Query history (144)
│   └── voice_runtime.json              # Voice state
│
├── memory/
│   └── index.jsonl                     # Memory proposals
│
└── logs/
    └── router/
        └── router_decisions.jsonl      # Router audit log
```

---

## Rollback & Safety

| Mechanism | How | When |
|-----------|-----|------|
| **Legacy rollback** | `LUCY_ROUTER_LEGACY_PRIMARY=1` | Embedding router malfunction |
| **Legacy audit** | Computed on every call, logged | Continuous validation |
| **Safety net** | `embedding_route`, `guards_fired`, `top_k_neighbours` in every log entry | Post-hoc analysis |
| **Auto-feedback** | Heuristic misroute detection | After every execution |
| **Log dir** | `LUCY_ROUTER_LOG_DIR=logs/router/` (set by runtime bridge) | Always |

---

*End of architecture document. Render Mermaid diagrams with any Mermaid-compatible viewer (GitHub, VS Code, mermaid.live).*
