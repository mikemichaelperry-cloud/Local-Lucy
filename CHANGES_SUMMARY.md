# Voice Pipeline Fixes - Summary

## Problems Fixed

### 1. LLM Restraints Missing (Augmented Completion Guard)
**Issue**: The Python router was missing the `augmented_completion_guard` that existed in the old shell script.

**Fix**: Added `_apply_augmented_completion_guard()` method to `local_answer.py` that:
- Removes dangling conjunctions (", and." → ".")
- Truncates to last complete sentence (≥40 chars)
- Closes truncated fragments with "."
- Tracks diagnostics: `triggered` and `reason`

**File**: `tools/router_py/local_answer.py`

### 2. "Spooky" Voice (Sample Rate Mismatch)
**Issue**: 
- Kokoro outputs at 24000 Hz
- Piper outputs at 22050 Hz
- aplay was configured for 24000 Hz, causing Piper audio to play fast/high-pitched

**Fix**:
- Changed `streaming_voice.py` sample rate to 22050 Hz (Piper-compatible)
- Added resampling from 24000 Hz → 22050 Hz in `streaming_tts_helper.py`

**Files**:
- `tools/router_py/streaming_voice.py`
- `tools/router_py/streaming_tts_helper.py`

### 3. Voice Inconsistency
**Issue**: Different default voices in different files:
- `voices.yaml`: "bf_emma"
- `streaming_voice.py`: "af_heart"
- `kokoro_backend.py`: "af_nicole"

**Fix**: Standardized all to "af_nicole"

**Files**:
- `tools/voice/voices/voices.yaml`
- `tools/router_py/streaming_voice.py`

### 4. Kokoro Worker Management
**Issue**: Worker needed to be manually started, and auto-start was complex/flaky.

**Fix**: Simplified architecture - `StreamingVoicePipeline` now manages the Kokoro worker as a subprocess:
- `KokoroWorkerManager` class handles worker lifecycle
- Worker started automatically when pipeline initializes
- Worker stopped when pipeline is destroyed
- Fallback to subprocess synthesis if worker fails

**Advantages**:
- No PID files needed
- No socket path discovery issues
- No daemonization complexity
- Worker lifecycle tied to pipeline lifecycle

**Files**:
- `tools/router_py/streaming_voice.py` (added `KokoroWorkerManager`)
- Removed: `tools/voice/kokoro_worker_manager.py`
- Removed: `tools/voice/start_kokoro_worker.sh`

### 5. HF Hub Warnings Corrupting PCM Audio
**Issue**: HuggingFace auth warnings were going to stdout, corrupting PCM audio data.

**Fix**: Suppressed warnings in `streaming_tts_helper.py`:
- Set `HF_HUB_DISABLE_SYMLINKS_WARNING=1`
- Set `TOKENIZERS_PARALLELISM=false`
- Disabled transformers/huggingface_hub loggers

**File**: `tools/router_py/streaming_tts_helper.py`

## Files Modified

1. `tools/router_py/local_answer.py` - Added augmented completion guard
2. `tools/router_py/streaming_voice.py` - Fixed sample rate, voice, added worker manager
3. `tools/router_py/streaming_tts_helper.py` - Added resampling, suppressed HF warnings
4. `tools/voice/voices/voices.yaml` - Standardized voice to "af_nicole"
5. `tools/voice/kokoro_session_worker.py` - Fixed import path

## Files Removed

1. `tools/voice/kokoro_worker_manager.py` - No longer needed
2. `tools/voice/start_kokoro_worker.sh` - No longer needed

## Testing

Test the voice pipeline:

```bash
# 1. The worker will auto-start when voice pipeline initializes
# 2. Test TTS synthesis:
echo '{"cmd":"synthesize","text":"Hello world","voice":"af_nicole"}' | \
  nc -U ~/lucy-v8/snapshots/opt-experimental-v8-dev/tmp/run/kokoro_tts_worker.sock

# 3. Full voice interaction:
# Press PTT button in HMI - pipeline will handle worker automatically
```

## Architecture Diagram

```
StreamingVoicePipeline
├── KokoroWorkerManager (new)
│   ├── Starts kokoro_session_worker.py as subprocess
│   ├── Manages socket lifecycle
│   └── Stops worker on cleanup
│
├── _synthesize_to_pcm()
│   ├── _synthesize_via_worker() (fast path)
│   └── _synthesize_subprocess_to_pcm() (fallback)
│
└── _stream_tts_continuous()
    └── aplay @ 22050 Hz (Piper-compatible)
```
