# Local Lucy v10 — Installation Guide

## Prerequisites

- Ubuntu 22.04/24.04 (other Linux distros may work but are not tested)
- Python 3.10+
- NVIDIA GPU with CUDA 12+ (optional but recommended)
- 8 GB+ free disk space
- 12 GB+ VRAM for GPU inference (or CPU-only mode)

## Quick Start

```bash
# 1. Clone
git clone https://github.com/mikemichaelperry-cloud/Local-Lucy.git ~/local-lucy
cd ~/local-lucy

# 2. Install system dependencies
sudo apt update
sudo apt install -y python3-venv python3-pip curl docker.io

# 3. Install Ollama
curl -fsSL https://ollama.com/install.sh | sh
ollama serve &

# 4. Pull the default model
ollama pull local-lucy-llama31

# 5. Install Lucy
make install

# 6. Verify environment
make check-env

# 7. Launch
make run
```

## Optional: SearXNG Search

```bash
cd services/searxng
bash start.sh
```

## Configuration

Copy `.env.example` to `.env` and fill in optional API keys:

```bash
cp .env.example .env
# Edit .env with your keys for OpenAI, Kimi, Brave Search, etc.
```

## Troubleshooting

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md).
