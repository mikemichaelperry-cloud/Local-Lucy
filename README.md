<div align="center">

# 🤖 Local Lucy V8

**A Self-Learning, Privacy-First Desktop AI Assistant**

[![CI](https://github.com/mikemichaelperry-cloud/Local-Lucy/actions/workflows/ci.yml/badge.svg)](https://github.com/mikemichaelperry-cloud/Local-Lucy/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-430%2B%20passing-brightgreen)](tools/router_py/)

[Features](#features) • [Installation](#installation) • [Usage](#usage) • [Architecture](#architecture) • [Contributing](CONTRIBUTING.md)

</div>

---

## Overview

Local Lucy V8 is a **privacy-first, self-learning desktop AI assistant** built with PySide6. It runs entirely on your local machine with optional cloud augmentation, giving you full control over your data while providing intelligent conversation, voice interaction, and real-time information retrieval.

Unlike cloud-only assistants, Lucy learns from your corrections in natural language — tell her "that should have been LOCAL" and she updates her routing model automatically.

## Features

### 🧠 Intelligent Routing
- **ModernBERT-base embedding router** (768-dim) with k-NN similarity for intent classification
- **Keyword guard rails** prevent misrouting on ambiguous short queries
- **Self-learning feedback loop** — natural language corrections rebuild the embedding index
- **Auto-feedback trust tiers** — separate confidence thresholds for user vs. auto-detected corrections

### 🎙️ Voice Interaction
- **Push-to-Talk (PTT)** with hold and tap modes
- **Whisper large-v3-turbo** for fast, accurate speech-to-text
- **Kokoro TTS** for natural-sounding voice output
- Async state machine with timeout guards

### 🔒 Privacy & Local-First
- **Primary LLM runs locally** via Ollama (Qwen3 14B)
- **Optional cloud augmentation** (Kimi/OpenAI) for complex queries
- **SQLite state management** with versioned schema migrations
- **Session memory** persists across restarts

### 📡 Live Data Integration
- **TIME** — Current time, timezone conversions, date queries
- **NEWS** — RSS feed aggregation with region filtering
- **WEATHER** — Real-time weather lookups
- **WIKIPEDIA** — Knowledge base queries
- **WEB SEARCH** — SearXNG integration

### 🖥️ Desktop HMI
- PySide6-based GUI with conversation history
- Real-time status panel and event logs
- Configurable voice and provider settings
- Cross-platform (Linux primary, extensible)

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  PySide6 HMI (ui-v8/app/)                                   │
│  ├─ ControlPanel — mode toggles, voice PTT                  │
│  ├─ ConversationPanel — draft input, history                │
│  ├─ StatusPanel — runtime metrics                           │
│  └─ EventLogPanel — engineering logs                        │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│  Lucy Core (tools/router_py/)                               │
│  ├─ Execution Engine — route dispatch & provider fallback   │
│  ├─ Hybrid Router — ModernBERT embeddings + keyword guards  │
│  ├─ Feedback Parser — NL correction detection               │
│  ├─ Background Learner — auto-rebuilds from feedback        │
│  └─ Schema Migrations — versioned SQLite evolution          │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│  Providers                                                  │
│  ├─ LOCAL — Ollama (Qwen3 14B)                              │
│  ├─ AUGMENTED — Kimi / OpenAI APIs                          │
│  ├─ TIME — TimeAPI.io                                       │
│  ├─ NEWS — RSS feeds                                        │
│  ├─ WEATHER — Weather APIs                                  │
│  └─ EVIDENCE — Wikipedia + Web Search                       │
└─────────────────────────────────────────────────────────────┘
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for the complete technical specification.

## Installation

### Prerequisites

- **Python** 3.10+
- **Ollama** — [Install from ollama.com](https://ollama.com)
- **Qt6 platform plugins** (for Linux: `qt6-base-dev` or equivalent)
- **GPU recommended** — RTX 3060 12GB or better for local LLM inference

> **Note:** On first run, the embedding router will auto-build its index from the bundled training examples (~645 queries). This takes 5–10 seconds and is saved to `models/router/comprehensive_embeddings.npy` for subsequent runs.
>
> **Disk space:** ~10 GB for the Ollama model + ~2 GB for PyTorch/Transformers pip packages.

### Quick Start

```bash
# Clone the repository
git clone git@github.com:mikemichaelperry-cloud/Local-Lucy.git
cd Local-Lucy

# Create a virtual environment
python3 -m venv ui-v8/.venv
source ui-v8/.venv/bin/activate

# Install dependencies
pip install -r ui-v8/requirements.txt

# Download the base model (~9.8 GB) and create the custom variants
ollama pull qwen3:14b
ollama create local-lucy -f config/Modelfile.local-lucy
ollama create local-lucy-fast -f config/Modelfile.local-lucy-fast

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

## Usage

### Natural Conversation

Just type or speak naturally. Lucy routes your query automatically:

| You say | Route | What happens |
|---------|-------|-------------|
| "What's the weather in Tokyo?" | WEATHER | Fetches live weather data |
| "Tell me about quantum computing" | LOCAL | Runs local LLM inference |
| "What are today's headlines?" | NEWS | Aggregates RSS feeds |
| "What time is it in Berlin?" | TIME | Timezone conversion |

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
| `LUCY_AUTO_LEARN_THRESHOLD` | 3 | User feedback entries before rebuild |
| `LUCY_AUTO_FEEDBACK_THRESHOLD` | 5 | Auto-feedback entries before rebuild |
| `LUCY_AUTO_FEEDBACK_MAX_CONFIDENCE` | 0.5 | Cap on auto-feedback confidence |
| `LUCY_ROUTER_LEGACY_PRIMARY` | 0 | Use legacy keyword router |

## Development

### Running Tests

```bash
# Full test suite (430+ tests)
source ui-v8/.venv/bin/activate
python3 -m pytest tools/router_py/ -q

# Router-specific tests
python3 -m pytest models/router/ -q

# End-to-end tests
python3 -m pytest tools/tests/test_end_to_end_comprehensive.py -q
```

### Project Structure

```
Local-Lucy/
├── ui-v8/                  # PySide6 desktop application
│   ├── app/                # HMI panels, backend bridge
│   └── requirements.txt    # Python dependencies
├── tools/router_py/        # Core execution engine & router
│   ├── main.py             # CLI entry point
│   ├── execution_engine.py # Provider dispatch
│   ├── classify.py         # Intent classification
│   ├── feedback_parser.py  # NL feedback detection
│   └── test_*.py           # Comprehensive test suite
├── models/router/          # Embedding model & learner
│   ├── hybrid_router.py    # ModernBERT routing
│   ├── background_learner.py
│   └── comprehensive_examples.json
├── tools/memory/           # Session memory service
├── tools/voice/            # STT/TTS pipeline
├── config/                 # Environment configs
├── scripts/                # Helper scripts
└── docs/                   # Design docs & reports
```

## Safety & Hardening

Local Lucy is designed with multiple safety layers:

- **Medical query heuristics** — High-risk medication queries are flagged and routed safely
- **Adversarial prompt testing** — 109+ prompts validated, 0 crashes
- **Embedding collapse detection** — Prevents ModernBERT [CLS] misrouting on short queries
- **Provider fallback chains** — Graceful degradation when APIs fail
- **Schema migrations** — Zero-downtime database evolution with rollback

See [docs/audits/AUDIT_REPORT_2026-05-07.md](docs/audits/AUDIT_REPORT_2026-05-07.md) for the full security audit.

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

- [ModernBERT](https://github.com/AnswerDotAI/ModernBERT) — Answer.AI for the embedding model
- [Ollama](https://ollama.com) — Local LLM serving
- [Kokoro](https://github.com/hexgrad/kokoro) — Fast, quality TTS
- [OpenAI Whisper](https://github.com/openai/whisper) — Speech recognition
- [PySide6](https://doc.qt.io/qtforpython/) — Qt bindings for Python
