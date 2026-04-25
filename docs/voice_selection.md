# Voice Selection Guide

## Current Default

**Engine:** Kokoro  
**Voice:** `bf_emma` (British Female, Emma)

Changed from `af_heart` (American) to `bf_emma` (British) on 2026-04-09.

---

## Available British Voices (Kokoro)

### Female (Recommended: bf_emma)
| Voice | Quality | Character |
|-------|---------|-----------|
| `bf_emma` | ★★★★★ | Clear, professional, warm |
| `bf_alice` | ★★★★☆ | Soft, pleasant |
| `bf_isabella` | ★★★★☆ | Youthful, bright |
| `bf_lily` | ★★★★☆ | Natural, conversational |

### Male
| Voice | Quality | Character |
|-------|---------|-----------|
| `bm_daniel` | ★★★★★ | Clear, authoritative |
| `bm_george` | ★★★★☆ | Warm, mature |
| `bm_fable` | ★★★★☆ | Storyteller quality |
| `bm_lewis` | ★★★☆☆ | Neutral |

---

## Changing Voice

### Option 1: Environment Variable (Temporary)
```bash
export LUCY_VOICE_KOKORO_VOICE=bf_lily
python app/main.py
```

### Option 2: Config File (Permanent)
Edit: `snapshots/opt-experimental-v7-dev/tools/voice/voices/voices.yaml`

```yaml
engines:
  kokoro:
    voice: bf_emma  # Change this
    fallback_engine: piper
```

### Option 3: Runtime Control
Not currently exposed in UI - use env var or config file.

---

## Voice File Sizes

Each voice is ~523 KB. First use downloads automatically from HuggingFace.

Cached location: `~/.cache/huggingface/hub/`

---

## Latency Impact

**None.** Voice selection has zero impact on latency:
- Same model (Kokoro-82M)
- Same inference speed
- Just swaps the voice tensor (~523KB)
- First download: ~1-2 seconds (one-time)
- Subsequent uses: cached locally

---

## Fallback Behavior

If Kokoro fails (e.g., worker not running), system falls back to:
- **Engine:** Piper
- **Voice:** `en_GB-cori-high` (British)

So you'll always get British accent even on fallback.
