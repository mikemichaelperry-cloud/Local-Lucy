<div align="center">

# 🤖 Local Lucy V10

**A Self-Learning, Privacy-First Desktop AI Assistant**

[![CI](https://github.com/mikemichaelperry-cloud/Local-Lucy/actions/workflows/ci.yml/badge.svg)](https://github.com/mikemichaelperry-cloud/Local-Lucy/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-1600%2B%20passing-brightgreen)](tools/router_py/)

[Features](#features) • [Installation](#installation) • [Usage](#usage) • [Architecture](#architecture) • [Contributing](CONTRIBUTING.md)

</div>

---

## Overview

Local Lucy V10 is a **privacy-first, self-learning desktop AI assistant** built with PySide6. It runs entirely on your local machine with optional cloud augmentation, giving you full control over your data while providing intelligent conversation, voice interaction, and real-time information retrieval.

Unlike cloud-only assistants, Lucy learns from your corrections in natural language — tell her "that should have been LOCAL" and she updates her routing model automatically.

> **Looking for the frozen V9 baseline?** Check out the [`local-lucy-v9-frozen-2026-05-28`](https://github.com/mikemichaelperry-cloud/Local-Lucy/releases/tag/local-lucy-v9-frozen-2026-05-28) tag.

## Features

### 🧠 Intelligent Routing
- **MiniLM-L6-v2 embedding router** (384-dim, ~900 examples) with k-NN similarity and semantic disambiguation
- **Four-stage pipeline**: structural safety → embedding k-NN → minimal keyword catches → calibrated confidence fallback
- **Self-learning feedback loop** — natural language corrections rebuild the embedding index
- **Auto-feedback trust tiers** — separate confidence thresholds for user vs. auto-detected corrections
- **V1 purge complete** — legacy keyword fortress removed; embedding router is the sole authority

### 🎙️ Voice Interaction
- **Push-to-Talk (PTT)** with hold and tap modes
- **Whisper large-v3-turbo** for fast, accurate speech-to-text
- **Kokoro TTS** for natural-sounding voice output
- Async state machine with timeout guards

### 🔒 Privacy & Local-First
- **Primary LLM runs locally** via Ollama (Qwen3 14B, ~2048-token context)
- **Optional cloud augmentation** (Kimi/OpenAI) for complex queries
- **SQLite state management** with versioned schema migrations
- **Session memory** persists across restarts

### 📡 Live Data Integration
- **LOCAL** — Default local LLM inference via Ollama
- **AUGMENTED** — Wikipedia → OpenAI → Kimi chain with evidence-backed answers
- **TIME** — Current time, timezone conversions, date queries
- **NEWS** — RSS feed aggregation with region filtering
- **WEATHER** — Real-time weather lookups

### 🖥️ Desktop HMI
- PySide6-based GUI with conversation history and detail view
- Real-time status panel and event logs
- Configurable voice, provider, and model settings
- Cross-platform (Linux primary, extensible)

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
│  ├─ Hybrid Router V2 — MiniLM-L6-v2 embeddings + keyword    │
│  ├─ Feedback Parser — NL correction detection               │
│  ├─ Background Learner — auto-rebuilds from feedback        │
│  └─ Schema Migrations — versioned SQLite evolution          │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│  Providers                                                  │
│  ├─ LOCAL — Ollama (Qwen3 14B)                              │
│  ├─ AUGMENTED — Wikipedia → OpenAI → Kimi                   │
│  ├─ TIME — TimeAPI.io                                       │
│  ├─ NEWS — RSS feeds                                        │
│  ├─ WEATHER — Weather APIs                                  │
│  └─ EVIDENCE — Wikipedia + citation requirement             │
└─────────────────────────────────────────────────────────────┘
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for the complete technical specification.

## Installation

### Prerequisites

- **Python** 3.10+
- **Ollama** — [Install from ollama.com](https://ollama.com)
- **Qt6 platform plugins** (for Linux: `qt6-base-dev` or equivalent)
- **GPU recommended** — RTX 3060 12GB or better for local LLM + Whisper GPU coexistence

> **Note:** On first run, the embedding router will auto-build its index from the bundled training examples (~899 queries). This takes 5–10 seconds and is saved to `models/router/comprehensive_embeddings.npy` for subsequent runs.
>
> **Disk space:** ~10 GB for the Ollama model + ~2 GB for PyTorch/Transformers pip packages.

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
# Default: qwen3:14b (~9.8 GB VRAM, good general performance)
ollama pull qwen3:14b
ollama create local-lucy -f config/Modelfile.local-lucy
ollama create local-lucy-fast -f config/Modelfile.local-lucy-fast

# Alternative: mistral-nemo 12B (~7.1 GB VRAM, faster inference)
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

## Usage

### Natural Conversation

Just type or speak naturally. Lucy routes your query automatically:

| You say | Route | What happens |
|---------|-------|-------------|
| "What's the weather in Tokyo?" | WEATHER | Fetches live weather data |
| "Tell me about quantum computing" | LOCAL | Runs local LLM inference |
| "What are today's headlines?" | NEWS | Aggregates RSS feeds |
| "What time is it in Berlin?" | TIME | Timezone conversion |
| "Amoxicillin dose for a 10kg dog" | AUGMENTED | Evidence-backed veterinary answer |

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
| `LUCY_RUNTIME_NAMESPACE_ROOT` | `~/.codex-api-home/lucy/runtime-v10` | Runtime state directory |
| `LUCY_RUNTIME_AUTHORITY_ROOT` | project root | Project root for contract validation |

## Development

### Running Tests

```bash
# Router core tests
source ui-v10/.venv/bin/activate
cd tools/router_py
python3 -m pytest test_classify.py test_execution_engine_state.py test_memory_gate.py -q

# UI offscreen tests
cd ui-v10
python3 -m pytest tests/ -q

# End-to-end smoke test
cd ui-v10
python3 e2e_smoke_test.py
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
│   ├── classify.py         # Intent classification (V2)
│   ├── local_answer.py     # Local LLM prompt builder
│   ├── feedback_parser.py  # NL feedback detection
│   └── test_*.py           # Comprehensive test suite
├── models/router/          # Embedding model & learner
│   ├── hybrid_router_v2.py # MiniLM-L6-v2 routing
│   ├── background_learner.py
│   ├── comprehensive_examples.json
│   └── finetuned_minilm/   # Optional fine-tuned model
├── tools/memory/           # Session memory service
├── tools/voice/            # STT/TTS pipeline
├── data/tubes/             # Vacuum tube database
├── config/                 # Environment configs, Modelfiles
├── scripts/                # Helper scripts
└── docs/                   # Design docs & reports
```

## Safety & Hardening

Local Lucy is designed with multiple safety layers:

- **Structural safety checks** — Empty, hostile, creative, and conspiracy input filtering
- **Medical/vet evidence policy** — High-risk queries require evidence_mode with citations
- **Adversarial prompt testing** — 469+ synthetic adversarial cases validated
- **Embedding-first routing** — No broad keyword fortress; semantic similarity decides
- **Provider fallback chains** — Graceful degradation when APIs fail
- **Schema migrations** — Zero-downtime database evolution with rollback
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
