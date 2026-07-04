# GPU Resource Allocation Report
Generated: 2026-04-09

## Hardware
- **GPU:** NVIDIA GeForce RTX 3060
- **VRAM:** 12 GB (12288 MiB)
- **CUDA Version:** 13.0
- **Driver:** 580.126.09

---

## Current Allocation

| Component | GPU Memory | Status | Device |
|-----------|-----------|--------|--------|
| **Kokoro TTS Worker** | ~1.9 GB | ✓ Active | CUDA (PyTorch) |
| **Ollama LLM** | ~4.4 GB | ✓ Active | CUDA (llama.cpp) |
| **Xorg Display** | ~157 MB | System | GPU |
| **GNOME Shell** | ~21 MB | System | GPU |
| **Free/Available** | ~5.5 GB | Headroom | - |
| **Total Used** | ~6.3 GB | 52% | - |

---

## Kokoro TTS (Voice)

### Configuration
- **Engine:** Kokoro-82M
- **Device:** CUDA (auto-detected)
- **Voice:** bf_emma (British Female)
- **Worker:** Persistent session worker

### GPU Verification
```python
PyTorch CUDA:   Available ✓
Device:         NVIDIA GeForce RTX 3060
Capability:     8.6 (Ampere)
Memory Used:    ~1.9 GB (persistent)
```

### Performance
- **Synthesis Speed:** ~1-2s for typical utterances
- **Quality:** High (neural TTS)
- **Latency Impact:** Minimal (pipeline warm)

---

## Ollama LLM

### Configuration
- **Model:** local-lucy-llama31 (llama3.1:8b)
- **Quantization:** Q4_K / Q6_K
- **Device:** CUDA (all layers)
- **GPU Layers:** 33/33 (100% offloaded)

### GPU Verification (from logs)
```
offloading 32 repeating layers to GPU
offloading output layer to GPU
offloaded 33/33 layers to GPU
CUDA0 model buffer size = 4403.49 MiB
```

### Performance
- **Context:** 4096 tokens
- **Inference:** GPU-accelerated
- **VRAM per Request:** ~4.4 GB base

---

## LoRA Training VRAM Requirements

Training persona LoRA adapters is more memory-intensive than inference. On the RTX 3060 12 GB, adapters must be trained one at a time.

| Base model | Parameters | LoRA config | VRAM on RTX 3060 12 GB |
|---|---|---|---|
| Llama 3.1 8B Instruct | ~8B | rank 16, seq 2048, 4-bit | ✅ Fits (~10 GB peak) |
| Mistral-Nemo-Instruct-2407 | ~12B | rank 8, seq 1024, 4-bit | ❌ OOM at `prepare_model_for_kbit_training` |
| Qwen3 14B | ~14B | rank 4, seq 512, 4-bit | ❌ OOM at `prepare_model_for_kbit_training` |

Because Mistral-Nemo 12B and Qwen3 14B cannot be trained on this GPU, those selectable tags (`local-lucy-mistral`, `local-lucy`, `local-lucy-fast`, `local-lucy-qwen3`) fall back to prompt-level persona injection at runtime. Only Llama 3.1 8B has trained LoRA adapters. See `docs/runbooks/PERSONAS.md` for the full status and training commands.

## Optimization Status

### ✓ Efficient Allocations
1. **Kokoro on CUDA** — Correctly using GPU for TTS
2. **Ollama 100% GPU** — All layers offloaded to GPU
3. **Sufficient Headroom** — 5.5 GB free for spikes

### Memory Management
- **Kokoro:** Persistent worker maintains warm pipeline
- **Ollama:** Keep-alive maintains model in VRAM
- **Total Usage:** ~52% of available VRAM (healthy)

---

## Environment Variables

### Kokoro GPU Settings
```bash
# Optional: Force CUDA device
export LUCY_VOICE_KOKORO_DEVICE=cuda  # Default: auto (cuda if available)

# Optional: GPU-specific cache
export LUCY_VOICE_KOKORO_CACHE_HOME="${HOME}/.cache/kokoro"
```

### Ollama GPU Settings
```bash
# Ollama uses GPU automatically if available
# Optional: Limit GPU layers (not recommended)
export OLLAMA_GPU_OVERHEAD=0
```

---

## Monitoring Commands

```bash
# Real-time GPU monitoring
nvidia-smi -l 1

# Check Kokoro worker GPU usage
nvidia-smi | grep kokoro_session_worker

# Check Ollama GPU usage
journalctl -u ollama -f | grep -E "(GPU|CUDA|offloaded)"

# PyTorch CUDA check (in venv)
cd /home/mike/lucy-v10/ui-v10 && source .venv/bin/activate
python -c "import torch; print(f'CUDA: {torch.cuda.is_available()}')"
```

---

## Troubleshooting

### Kokoro Falls Back to CPU
**Symptoms:** Slow TTS, no GPU memory usage
**Fix:**
```bash
# Check PyTorch CUDA
python -c "import torch; print(torch.cuda.is_available())"

# Restart Kokoro worker
pkill -f kokoro_session_worker
cd /home/mike/lucy/snapshots/opt-experimental-v7-dev
python3 tools/voice/kokoro_session_worker.py serve
```

### Ollama Not Using GPU
**Symptoms:** High CPU usage, slow inference
**Fix:**
```bash
# Check Ollama logs
journalctl -u ollama -n 100 | grep -i gpu

# Restart Ollama
sudo systemctl restart ollama
```

### Out of Memory
**Symptoms:** Crashes, CUDA OOM errors
**Solutions:**
1. Close other GPU applications
2. Reduce Ollama context size
3. Use smaller Whisper model

---

## Summary

| Metric | Value | Status |
|--------|-------|--------|
| GPU Utilization | 52% | ✓ Good |
| Kokoro on CUDA | Yes | ✓ Optimized |
| LLM on GPU | 100% layers | ✓ Optimized |
| Free VRAM | 5.5 GB | ✓ Safe |

**Verdict:** Both Kokoro and LLM are efficiently using GPU resources with healthy headroom.
