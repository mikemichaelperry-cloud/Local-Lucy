# Voice System Timings & Timeouts

## PTT (Push-To-Talk) Timeout

**Value:** 150 seconds  
**Location:** `ui-v7/app/services/runtime_bridge.py:75`

### Why 150 seconds?

The PTT timeout must accommodate the complete voice round-trip:

```
[PTT Release] 
    → [Voice recording] 
    → [Whisper transcription] 
    → [Backend request: 125s max] 
    → [TTS synthesis] 
    → [Audio playback]
```

Breakdown:
- Whisper transcription: ~1-5s (depends on model and audio length)
- Backend request timeout: 125s (fixed)
- TTS synthesis: ~1-3s (Kokoro is faster than Piper)
- Audio playback: Variable (depends on response length)
- Overhead margin: ~10-15s

### Comparison

| Timeout | Use Case |
|---------|----------|
| 30s | Too short - backend alone can take 125s |
| 150s | **Current** - accommodates full pipeline |

### Code Reference

```python
# ui-v7/app/services/runtime_bridge.py
self.voice_stop_timeout_seconds = 150  # Must accommodate: transcription + backend request (125s) + TTS + overhead
```

---

## TTS Engine Comparison

### Kokoro (Active/Default)

- **Status:** Primary engine
- **Speed:** Faster than Piper (~30-50% improvement)
- **Quality:** High quality neural TTS
- **Worker:** Persistent session worker (`kokoro_session_worker.py`)
- **Voice:** `bf_emma` (British Female) - high quality, clear articulation
- **Sample Rate:** 24000 Hz
- **Alternative Voices:** `bf_lily`, `bm_daniel`, `bm_george` (see voices.yaml)

### Piper (Fallback)

- **Status:** Fallback when Kokoro unavailable
- **Speed:** Slower but reliable
- **Quality:** Good quality, lower resource usage
- **Voice:** `en_GB-cori-high`
- **Sample Rate:** 22050 Hz

---

## Typical Latencies (Measured)

### Text Mode (TTC = Time To Completion)

| Query Type | Median TTC |
|------------|-----------|
| Simple fact | 1.2s |
| Explanation | 2.8s |
| Recipe/technical | 4.5s |

### Voice Mode

| Stage | Duration |
|-------|----------|
| Transcription (small.en) | ~1-3s |
| Text generation | Same as text mode |
| TTS (Kokoro, short) | ~0.5-1s |
| TTS (Kokoro, medium) | ~1-2s |
| First audio playback | ~0.3ms after synthesis |

---

## Timeout Hierarchy

```
Backend request timeout:    125s  (tools/runtime_request.py)
PTT/voice timeout:          150s  (ui-v7/app/services/runtime_bridge.py)
Control operations:           5s  (mode, features)
Profile operations:           5s  (reload)
Lifecycle operations:        15s  (start/stop)
Voice status check:           5s
Voice start:                  5s
```

---

## Optimization Notes

1. **Kokoro Worker Warmup:** The persistent Kokoro session worker maintains a warm pipeline, eliminating cold-start delays.

2. **First-Chunk Priming:** Recent fixes (April 2025) added player priming to prevent clipped first words.

3. **Early TTS:** First sentence synthesis starts before full answer completion for faster voice response.

4. **Model Selection:**
   - Current: `small.en` (488 MB) - good accuracy/speed balance
   - Options: `base.en` (~150 MB, faster), `tiny.en` (~75 MB, fastest but less accurate)

---

*Last updated: 2026-04-09*
