# Voice Cutoff Diagnostic Report

**Date**: 2026-04-17  
**Status**: Simulation tests completed - Issue NOT reproduced in isolation

---

## Executive Summary

After extensive simulation testing, **the basic voice pipeline mechanism is sound**. All tests pass:
- ✓ Basic aplay/paplay usage
- ✓ Phrase-by-phrase streaming
- ✓ 24kHz → 22kHz resampling (Kokoro simulation)
- ✓ Variable synthesis delays (100-300ms gaps)
- ✓ Long content (20+ phrases)
- ✓ Various buffer sizes
- ✓ Race conditions

**Conclusion**: The cutoff issue is likely specific to the **actual Kokoro TTS** or **integration environment**, not the basic streaming mechanism.

---

## Test Results

### 1. Audio Backend Comparison

| Method | Status | Notes |
|--------|--------|-------|
| aplay | PASS | Works with all buffer sizes (32K-128K) |
| paplay | PASS | Slightly faster timing, needs WAV format |
| pw-play | FAIL | BrokenPipeError (system uses PulseAudio, not PipeWire) |

**Recommendation**: Stick with `aplay` or switch to `paplay` with proper WAV wrapping.

### 2. Buffer Configuration

| Buffer Size | Result |
|-------------|--------|
| 32768 | OK |
| 65536 (current) | OK |
| 131072 | OK |

**No buffer underruns detected** in any test.

### 3. Resampling Test (24kHz → 22.05kHz)

- Source: 24kHz WAV (Kokoro native rate)
- Target: 22.05kHz PCM (aplay rate)
- Method: Linear interpolation (numpy)
- Result: **PASS** - No audio glitches

### 4. Long Content Stress Test

- 15 phrases, ~14s of audio
- With synthesis delays (100-300ms)
- Result: **PASS** - Playback completed in expected time

### 5. Race Condition Tests

| Test | Result |
|------|--------|
| Early cancel() | Handled gracefully |
| Write after close | Detected error |
| 50 small writes | OK |
| aplay death mid-stream | Error caught |
| Real-world timing | OK (7.5s actual vs 7.0s expected) |

---

## Potential Root Causes (Hypotheses)

Since simulation tests pass, the issue is likely in one of these areas:

### Hypothesis 1: Kokoro Worker Communication
**Likelihood**: High

The `_synthesize_via_worker()` function uses Unix domain sockets. If the worker:
- Times out during synthesis
- Returns partial audio
- Closes socket early
- Has memory issues with long text

...it could cause phrases to be missing from the stream.

**Evidence**: Simulation uses pre-generated audio, bypassing the worker.

### Hypothesis 2: Subprocess Fallback
**Likelihood**: Medium

If the Kokoro worker fails, code falls back to `_synthesize_subprocess_to_pcm()`. This:
- Spawns a new Python process per phrase
- Could have timing issues
- May not handle long text well

**Code location**: `streaming_voice.py` lines 540-568

### Hypothesis 3: Resampling Edge Cases
**Likelihood**: Low

The numpy linear interpolation resampling (lines 516-533) could:
- Fail on certain audio patterns
- Introduce artifacts that confuse aplay
- Be slow enough to cause gaps

**Evidence**: Tests show resampling works correctly.

### Hypothesis 4: System-Specific Issues
**Likelihood**: Medium

- ALSA/PulseAudio configuration
- Audio hardware buffer underruns under load
- RTX 3060 specific audio issues
- Other processes competing for audio

### Hypothesis 5: Trailing Silence Not Sufficient
**Likelihood**: Low

Current: 2000ms trailing silence + 2500ms wait = 4.5s buffer

But if aplay's internal buffer is larger than expected, this might not be enough.

---

## Recommended Fixes

### Fix 1: Use `paplay` Instead of `aplay` (RECOMMENDED)

`paplay` is PulseAudio-native and may have better buffer management:

```python
# In streaming_voice.py, replace aplay with paplay
# paplay accepts WAV directly, no need for raw format flags

proc = await asyncio.create_subprocess_exec(
    "paplay",
    stdin=subprocess.PIPE,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)

# Wrap PCM in WAV header
import io, wave
wav_buffer = io.BytesIO()
with wave.open(wav_buffer, 'wb') as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(22050)
    w.writeframes(pcm_data)
proc.stdin.write(wav_buffer.getvalue())
```

### Fix 2: Verify All Phrases Received

Add validation to ensure phrases aren't lost:

```python
async def _stream_tts_continuous(self, ...):
    phrases_synthesized = []
    phrases_received = []
    
    for phrase in phrases:
        audio = await self._synthesize_to_pcm(phrase)
        phrases_synthesized.append(phrase)
        if audio:
            aplay_proc.stdin.write(audio)
            phrases_received.append(phrase)
    
    # Log discrepancy
    if len(phrases_received) < len(phrases_synthesized):
        print(f"[TTS Warning] Only {len(phrases_received)}/{len(phrases_synthesized)} phrases received")
```

### Fix 3: Increase Wait Time

Try increasing wait time from 2.5s to 5s:

```python
# Line 441 in streaming_voice.py
await asyncio.sleep(5.0)  # Was 2.5s
```

### Fix 4: Use Blocking Wait Instead of Sleep

Replace sleep with proper process wait:

```python
# Instead of:
await asyncio.sleep(2.5)
aplay_proc.stdin.close()
await asyncio.wait_for(aplay_proc.wait(), timeout=10.0)

# Try:
aplay_proc.stdin.close()
await aplay_proc.wait()  # Block until aplay actually finishes
```

### Fix 5: Add Debug Logging

Add more detailed logging to identify where cutoff occurs:

```python
print(f"[TTS Debug] Phrases expected: {len(phrases)}")
print(f"[TTS Debug] Phrases synthesized: {phrases_synthesized}")
print(f"[TTS Debug] Audio bytes sent: {total_bytes}")
print(f"[TTS Debug] Expected duration: {expected_duration}s")
```

---

## Next Steps for Debugging

### Step 1: Test with Real Kokoro
Run a real voice query and capture debug output:
```bash
cd ~/lucy-v8/snapshots/opt-experimental-v8-dev
python3 tools/voice/tts_adapter.py synthesize "This is a long test message with many words to see if the voice cuts off before finishing"
```

### Step 2: Enable Verbose Logging
Modify `streaming_voice.py` to:
1. Log every phrase sent to aplay
2. Log total bytes written
3. Log aplay stderr for underruns

### Step 3: Test paplay Alternative
Replace aplay with paplay in `streaming_voice.py` and test:
```python
# Temporary change for testing
"paplay"  # instead of "aplay"
```

### Step 4: Monitor System Audio
Check for system-level issues:
```bash
# Check for underruns
pactl list | grep -i underrun

# Check audio latency
pactl list | grep -A5 "Latency"

# Check CPU load during voice playback
top -p $(pgrep -d',' aplay)
```

### Step 5: Test with Different Hardware
If possible, test on a different audio output:
- USB headphones instead of HDMI
- Different sample rate

---

## Files Created

1. `test_cutoff_diagnostic.py` - Basic audio backend tests
2. `test_streaming_phrases.py` - Phrase-by-phrase streaming test
3. `test_exact_pipeline.py` - Exact code path simulation
4. `test_kokoro_simulation.py` - Kokoro-specific tests (resampling, gaps)
5. `test_deep_analysis.py` - Verbose aplay, buffer analysis
6. `test_race_conditions.py` - Race condition tests

---

## Quick Fix to Try Now

If you want to try a fix immediately, here's a minimal change:

**File**: `tools/router_py/streaming_voice.py`
**Lines**: 441-446

Replace:
```python
await asyncio.sleep(2.5)

# Close stdin and wait for aplay to finish
aplay_proc.stdin.close()
try:
    await asyncio.wait_for(aplay_proc.wait(), timeout=10.0)
```

With:
```python
# Close stdin first to signal EOF
aplay_proc.stdin.close()

# Wait for aplay to actually finish playing
# This is more reliable than fixed sleep
try:
    await asyncio.wait_for(aplay_proc.wait(), timeout=30.0)
except asyncio.TimeoutError:
    print("[TTS Debug] aplay wait timeout, killing")
    aplay_proc.kill()
    await aplay_proc.wait()
```

This removes the fixed 2.5s sleep and instead waits for aplay to actually exit, which should only happen after all audio is played.

---

**Report Generated**: 2026-04-17  
**Tests Run**: 30+ scenarios  
**Status**: Ready for production testing with real Kokoro
