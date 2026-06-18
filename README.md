<div align="center">

# 🤖 Local Lucy V10

**A Self-Learning, Privacy-First Desktop AI Assistant**

[![CI](https://github.com/mikemichaelperry-cloud/Local-Lucy/actions/workflows/ci.yml/badge.svg)](https://github.com/mikemichaelperry-cloud/Local-Lucy/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-900%2B%20passing-brightgreen)](tools/router_py/)

[Features](#features) • [Installation](#installation) • [Usage](#usage) • [Architecture](#architecture) • [Contributing](CONTRIBUTING.md)

</div>

---

## Overview

Local Lucy V10 is a **privacy-first, self-learning desktop AI assistant** built with PySide6. It runs entirely on your local machine with optional cloud augmentation, giving you full control over your data while providing intelligent conversation, voice interaction, and real-time information retrieval.

Unlike cloud-only assistants, Lucy learns from your explicit corrections in natural language — tell her "that should have been LOCAL" and, after a safety gate, she updates her routing model. Auto-detected signals and router logs are telemetry only; they never mutate the model unsupervised.

> **Looking for the frozen V9 baseline?** Check out the [`local-lucy-v9-frozen-2026-05-28`](https://github.com/mikemichaelperry-cloud/Local-Lucy/releases/tag/local-lucy-v9-frozen-2026-05-28) tag.

## Features

### 🧠 Intelligent Routing
- **MiniLM-L6-v2 embedding router** (384-dim, ~1,019 examples) with k-NN similarity and semantic disambiguation
- **Four-stage pipeline**: structural safety → embedding k-NN → safety keyword guards → calibrated confidence fallback
- **Self-learning feedback loop** — explicit user corrections rebuild the embedding index after a safety gate
- **High-stakes review queue** — medical, veterinary, finance, legal, and EVIDENCE feedback goes to `pending_review.jsonl` for human review
- **V1 purge complete** — legacy broad keyword fortress removed; embedding router is the authority, with keyword guards retained only for safety-critical categories

### 🎙️ Voice Interaction
- **Push-to-Talk (PTT)** with hold and tap modes
- **Whisper large-v3-turbo** for fast, accurate speech-to-text
- **Kokoro TTS** for natural-sounding voice output
- Async state machine with timeout guards

### 🔒 Privacy & Local-First
- **Primary LLM runs locally** via Ollama (`local-lucy-llama31`, llama3.1:8b, 4096-token context)
- **Optional cloud augmentation** (Kimi/OpenAI) for complex queries
- **SQLite state management** with versioned schema migrations and `0o600` permissions
- **XDG-compliant runtime paths** (`~/.local/share/local-lucy`) with legacy fallback
- **Session memory** persists across restarts

### 📡 Live Data Integration
- **LOCAL** — Default local LLM inference via Ollama
- **AUGMENTED** — Web search → OpenAI → Kimi chain with evidence-backed answers
- **EVIDENCE** — Medical/vet/finance/legal queries with trusted-source citations
- **FINANCE** — Live FX, crypto, stock/index, and net-worth lookups with source citations
- **TIME** — Current time, timezone conversions, date queries
- **NEWS** — RSS feed aggregation with region filtering
- **WEATHER** — Real-time weather lookups

### 🖥️ Desktop HMI
- PySide6-based GUI with conversation history and detail view
- Real-time status panel and event logs
- Configurable voice, provider, and model settings
- Cross-platform (Linux primary, extensible)

### 🌐 Optional Web Interface
- Lightweight aioHTTP adapter for remote text access
- Reuses the same Local Lucy query pipeline as the PyQt HMI
- Stateless by default — no conversation memory shared with the desktop HMI
- Request-scoped model selection, validated against configured models
- Basic/Bearer authentication; loopback-only by default
- Mobile-friendly single-page UI

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  PySide6 HMI (ui-v10/app/)                                   │
│  ├─ ControlPanel — mode toggles, voice PTT, model selector  │
│  ├─ ConversationPanel — draft input, history, detail view   │
│  ├─ StatusPanel — runtime metrics, route confidence         │
│  └─ EventLogPanel — engineering logs                        │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│  Lucy Core (tools/router_py/)                               │
│  ├─ Execution Engine — route dispatch & provider fallback   │
│  ├─ Classify — embedding k-NN + safety keyword guards       │
│  ├─ Feedback Parser — NL correction detection               │
│  ├─ Background Learner — user-feedback-only index rebuilds  │
│  ├─ Structured Logging — JSON log output starter            │
│  └─ Schema Migrations — versioned SQLite evolution          │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│  Providers                                                  │
│  ├─ LOCAL — Ollama (llama3.1:8b default)                    │
│  ├─ AUGMENTED — Web search → OpenAI → Kimi                  │
│  ├─ EVIDENCE — Trusted sources + citations                  │
│  ├─ FINANCE — Live FX / crypto / stocks / net worth         │
│  ├─ TIME — TimeAPI.io                                       │
│  ├─ NEWS — RSS feeds                                        │
│  └─ WEATHER — Weather APIs                                  │
└─────────────────────────────────────────────────────────────┘
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for the complete technical specification.

## Installation

### Prerequisites

- **Python** 3.10+
- **Ollama** — [Install from ollama.com](https://ollama.com)
- **Qt6 platform plugins** (for Linux: `qt6-base-dev` or equivalent)
- **GPU recommended** — RTX 3060 12GB or better for local LLM + Whisper GPU coexistence

> **Note:** On first run, the embedding router will auto-build its index from the bundled training examples (~1,019 queries). This takes 5–10 seconds and is saved to `models/router/comprehensive_embeddings.npy` for subsequent runs.
>
> **Disk space:** ~8–10 GB for the Ollama model + ~2 GB for PyTorch/Transformers pip packages.

### Quick Start

```bash
# Clone the repository
git clone git@github.com:mikemichaelperry-cloud/Local-Lucy.git
cd Local-Lucy

# Create a virtual environment
python3 -m venv ui-v10/.venv
source ui-v10/.venv/bin/activate

# Install dependencies
pip install -r ui-v10/requirements.txt

# Download the base models and create the custom variants
# Default: llama3.1:8b (~8.5 GB VRAM, 4096-token context, follows system prompts)
ollama pull llama3.1:8b
ollama create local-lucy-llama31 -f config/Modelfile.local-lucy-llama31

# Legacy options (still selectable in the HMI)
ollama pull qwen3:14b
ollama create local-lucy -f config/Modelfile.local-lucy
ollama create local-lucy-fast -f config/Modelfile.local-lucy-fast

ollama pull mistral-nemo
ollama create local-lucy-mistral -f config/Modelfile.local-lucy-mistral

# (Optional) Copy and configure API keys for cloud providers
cp .env.example .env
# Edit .env and add your keys

# Launch the desktop application
./START_LUCY.sh
```

### CLI Mode

```bash
# Start in terminal chat mode
./lucy_chat.sh
```

### Web Interface (optional)

```bash
# Start the standalone web adapter
source ui-v10/.venv/bin/activate
LUCY_WEB_ENABLED=1 python -m web_adapter

# Open in a browser
http://127.0.0.1:8765
```

For LAN/Tailscale access, set `LUCY_WEB_HOST` and a token:

```bash
export LUCY_WEB_HOST=100.64.0.1
export LUCY_WEB_AUTH_TOKEN=$(openssl rand -hex 32)
LUCY_WEB_ENABLED=1 python -m web_adapter
```

See [docs/web_interface.md](docs/web_interface.md) for full security and configuration details.

## Usage

### Natural Conversation

Just type or speak naturally. Lucy routes your query automatically:

| You say | Route | What happens |
|---------|-------|-------------|
| "What's the weather in Tokyo?" | WEATHER | Fetches live weather data |
| "Tell me about quantum computing" | LOCAL | Runs local LLM inference |
| "What are today's headlines?" | NEWS | Aggregates RSS feeds |
| "What time is it in Berlin?" | TIME | Timezone conversion |
| "Bitcoin price" | FINANCE | Live crypto quote with source citation |
| "Amoxicillin dose for a 10kg dog" | EVIDENCE | Evidence-backed veterinary answer |

### Teaching Lucy

When Lucy gets a route wrong, just tell her:

```
You: Who is my dog?
Lucy: [routes to TIME — wrong]
You: Incorrect, the correct routing is LOCAL
Lucy: [learns — next time routes to LOCAL]
```

The background learner automatically rebuilds the embedding index from corrections.

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LUCY_LOCAL_MODEL` | `local-lucy-llama31` | Default Ollama model |
| `LUCY_AUTO_LEARN` | `1` | Allow background learning from explicit user feedback |
| `LUCY_RUNTIME_NAMESPACE_ROOT` | `~/.local/share/local-lucy` | XDG runtime state directory |
| `LUCY_RUNTIME_AUTHORITY_ROOT` | project root | Project root for contract validation |
| `LUCY_OLLAMA_API_URL` | `http://127.0.0.1:11434/api/generate` | Local LLM endpoint |
| `LUCY_WEB_ENABLED` | `0` | Set to `1` to start the optional web adapter |
| `LUCY_WEB_HOST` | `127.0.0.1` | Web adapter bind address |
| `LUCY_WEB_PORT` | `8765` | Web adapter bind port |
| `LUCY_WEB_AUTH_TOKEN` | *(none)* | Required token for non-loopback binds |

### Deprecated / Legacy Options

These options are preserved for backward compatibility but are no longer needed in V10. They will be removed in a future release.

| Variable | Status | Notes |
|----------|--------|-------|
| `LUCY_ROUTER_PY` | **Deprecated** | Python router is the only supported router in V10. |
| `LUCY_EXEC_PY` | **Deprecated** | Python execution engine is the only supported engine in V10. |
| `LUCY_ROUTER_LEGACY_PRIMARY=1` | **Deprecated / non-functional** | Keyword-router rollback is no longer supported; the embedding router is the sole authority. |

## Development

### Running Tests

```bash
# Full suite (~4 min)
cd ~/lucy-v10
source ui-v10/.venv/bin/activate
make test

# Router suite only
python -m pytest tools/router_py/ -q

# Web adapter tests
python -m pytest web_adapter/test_web_adapter.py -v

# Medical routing specifically
python -m pytest tools/router_py/test_medical_evidence_routing.py -v

# HMI offscreen tests
QT_QPA_PLATFORM=offscreen python3 ui-v10/tests/test_comprehensive_hmi_inspection.py

# End-to-end smoke test
python3 -c "import sys; sys.path.insert(0,'tools'); from router_py.main import execute_plan_python; \
  r = execute_plan_python('What is 2+2?', timeout=30); print(r.status, r.route)"
```

### Project Structure

```
Local-Lucy/
├── ui-v10/                  # PySide6 desktop application
│   ├── app/                # HMI panels, backend bridge, services
│   ├── tests/              # Offscreen UI regression tests
│   └── requirements.txt    # Python dependencies
├── tools/router_py/        # Core execution engine & router
│   ├── main.py             # CLI entry point
│   ├── execution_engine.py # Provider dispatch
│   ├── classify.py         # Intent classification + safety guards
│   ├── local_answer.py     # Local LLM prompt builder
│   ├── logging_config.py   # Structured JSON logging
│   ├── feedback_parser.py  # NL feedback detection
│   └── test_*.py           # Comprehensive test suite
├── models/router/          # Embedding model & learner
│   ├── hybrid_router_v2.py # MiniLM-L6-v2 routing
│   ├── background_learner.py
│   ├── auto_feedback.py    # Telemetry-only auto-feedback
│   ├── comprehensive_examples.json
│   └── pending_review.jsonl
├── tools/memory/           # Session memory service
├── tools/voice/            # STT/TTS pipeline
├── tools/internet/         # Web search & circuit breakers
├── tools/xdg_paths.py      # XDG path resolution
├── web_adapter/            # Optional HTTP/web UI adapter
├── packaging/              # .deb and AppImage build scripts
├── data/tubes/             # Web extraction pipelines
├── config/                 # Environment configs, Modelfiles
├── scripts/                # Helper scripts (check_environment, migrate_db)
├── docs/                   # Design docs, ADRs, runbooks
├── START_LUCY.sh           # Desktop launcher
└── lucy_chat.sh            # CLI chat entry point
```

## Safety & Hardening

Local Lucy is designed with multiple safety layers:

- **Structural safety checks** — Empty, hostile, creative, and conspiracy input filtering
- **Medical/vet/finance/legal evidence policy** — High-risk queries route to `EVIDENCE`/`FINANCE` with citations
- **User-feedback-only learning** — Auto-feedback and router logs are telemetry-only; only explicit corrections are ingested
- **High-stakes review queue** — Medical, veterinary, finance, legal, and conflicting feedback goes to `pending_review.jsonl`
- **Embedding-first routing** — No broad keyword fortress; semantic similarity decides, with keyword guards for safety categories
- **Provider fallback chains** — Graceful degradation when APIs fail; fallback sources are labelled
- **Schema migrations** — Zero-downtime database evolution with rollback
- **SQLite permission hardening** — `lucy_state.db` and `memory.db` created with `0o600`
- **HTML/plain-text isolation** — QTextBrowser document state cleared between entries

## Contributing

We welcome contributions! Please read [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on:

- Setting up your development environment
- Running the test suite
- Submitting pull requests
- Commit message conventions

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for version history and release notes.

## License

Local Lucy is released under the [MIT License](LICENSE).

## Acknowledgments

- [Sentence Transformers](https://www.sbert.net/) — MiniLM-L6-v2 embedding model
- [Ollama](https://ollama.com) — Local LLM serving
- [Kokoro](https://github.com/hexgrad/kokoro) — Fast, quality TTS
- [OpenAI Whisper](https://github.com/openai/whisper) — Speech recognition
- [PySide6](https://doc.qt.io/qtforpython/) — Qt bindings for Python
