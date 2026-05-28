# Voice Model Assets

Local Lucy v8 supports three voice engines. Each requires specific on-disk assets.
This document describes what is needed, where it goes, and how to obtain it.

> **Note:** Model binaries are **not** tracked in Git. They are downloaded after clone.
> Text chat works out-of-the-box. Voice requires these additional assets.

---

## Quick Start

```bash
# Verify what you have and what's missing
python tools/voice/download_assets.py --verify-only

# Download all missing voice assets
python tools/voice/download_assets.py --download-all

# Or download selectively
python tools/voice/download_assets.py --download-whisper --model large-v3-turbo
python tools/voice/download_assets.py --download-piper --piper-voice en_GB-cori-high
```

---

## Asset Inventory

### 1. Whisper STT (Speech-to-Text)

Whisper uses GGML-format models from the `ggerganov/whisper.cpp` HuggingFace repository.

| Model | Size | Use case |
|-------|------|----------|
| `tiny.en` | ~75 MB | Fastest, lowest accuracy |
| `base.en` | ~150 MB | Fast, good accuracy |
| `small.en` | ~488 MB | **Default** — balanced speed/accuracy |
| `medium.en` | ~1.5 GB | Slower, high accuracy |
| `large-v3-turbo` | ~1.6 GB | Best accuracy, GPU recommended |

**Location:** `runtime/voice/models/ggml-<model>.bin`

**Env override:** `LUCY_VOICE_WHISPER_MODEL` (absolute path to a specific GGML file)

**Download source:** `https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-<model>.bin`

---

### 2. Kokoro TTS (Text-to-Speech)

Kokoro is a Python-native TTS engine. It downloads its own model files automatically
via the HuggingFace `hub` library on first use. No manual download is required.

**Cache location:** `runtime/voice/cache/huggingface/hub/models--hexgrad--Kokoro-82M/`

**Default voice:** `af_bella`

**Env overrides:**
- `HF_HOME` or `LUCY_VOICE_KOKORO_CACHE_HOME` — cache directory
- `LUCY_VOICE_KOKORO_VOICE` — voice selection
- `LUCY_VOICE_KOKORO_REPO_ID` — model repo (default: `hexgrad/Kokoro-82M`)

**On first run**, the following files are cached (~313 MB total):
- `kokoro-v1_0.pth` (~312 MB)
- `config.json` (~2 KB)
- `voices/af_bella.pt` (~512 KB)

---

### 3. Piper TTS (Text-to-Speech)

Piper uses ONNX voice models. These must be downloaded manually or via the asset tool.

**Default voice:** `en_GB-cori-high`

**Location:**
- ONNX model: `runtime/voice/models/piper/<voice>/<voice>.onnx`
- Config JSON: `runtime/voice/models/piper/<voice>/<voice>.onnx.json`

**Env override:** `LUCY_VOICE_PIPER_MODEL` (absolute path to ONNX file)

**Download source:**
- ONNX: `https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/cori/high/en_GB-cori-high.onnx`
- JSON: `https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/cori/high/en_GB-cori-high.onnx.json`

---

## Full Installation

For a complete voice setup including compiled binaries, run:

```bash
bash tools/install_voice_engines.sh
```

This script:
1. Installs system packages (`ffmpeg`, `cmake`, `alsa-utils`, etc.)
2. Clones and builds `whisper.cpp`
3. Downloads the Whisper GGML model
4. Installs Piper (Python package or legacy tarball)
5. Downloads the Piper voice model
6. Installs Kokoro Python dependencies into the `ui-v10` venv

After installation, verify with:

```bash
bash tools/verify_voice_engines.sh
```

---

## Verification Commands

### Check all voice assets
```bash
python tools/voice/download_assets.py --verify-only
```

### JSON output (for scripting)
```bash
python tools/voice/download_assets.py --verify-only --json
```

### Check specific Whisper model
```bash
python tools/voice/download_assets.py --verify-only --model large-v3-turbo
```

### Check specific Piper voice
```bash
python tools/voice/download_assets.py --verify-only --piper-voice en_GB-cori-high
```

---

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `LUCY_VOICE_MODEL` | `small.en` | Whisper model name |
| `LUCY_VOICE_WHISPER_MODEL` | *(derived)* | Absolute path to Whisper GGML file |
| `LUCY_VOICE_PIPER_VOICE` | `en_GB-cori-high` | Piper voice name |
| `LUCY_VOICE_PIPER_MODEL` | *(derived)* | Absolute path to Piper ONNX file |
| `LUCY_VOICE_KOKORO_VOICE` | `af_bella` | Kokoro voice name |
| `LUCY_VOICE_KOKORO_REPO_ID` | `hexgrad/Kokoro-82M` | HuggingFace repo for Kokoro |
| `HF_HOME` | `runtime/voice/cache/huggingface` | HuggingFace cache root |
| `LUCY_VOICE_INSTALL_PREFIX` | `runtime/voice` | Base directory for all voice assets |

---

## Git Ignore

The following paths are already ignored in `.gitignore`:

```gitignore
# Runtime downloads
runtime/voice/models/
```

This ensures model binaries are never committed. The `runtime/voice/` directory
itself is not ignored so that symlinks (e.g. `bin/whisper`, `bin/piper`) can be
re-created by the install script.

---

## CI / Automation Note

Voice model downloads are **skipped in CI**. The `download_assets.py` script can be
used in CI with `--verify-only` to confirm asset paths are configured correctly,
but `--download-all` should not be used in automated CI pipelines due to model size.
