# Local Lucy Pathways Reference

## Python Environments
- System Python: `/usr/bin/python3`
- UI Venv (has Kokoro): `/home/mike/lucy-v8/ui-v8/.venv/bin/python3`

## Critical Paths
- Project Root: `/home/mike/lucy-v8/snapshots/opt-experimental-v8-dev`
- Kokoro Socket: `tmp/run/kokoro_tts_worker.sock`
- Logs: `~/.local/share/lucy/logs/`

## Key Files
- local_answer.py: `tools/router_py/local_answer.py`
- voice_tool.py: `tools/router_py/voice_tool.py`
- voice_runtime.py: `tools/router_py/voice_runtime.py` (NEW - Python voice runtime)
- execution_engine.py: `tools/router_py/execution_engine.py`
- tts_adapter.py: `tools/voice/tts_adapter.py`
- kokoro_backend.py: `tools/voice/backends/kokoro_backend.py`
- streaming_voice.py: `tools/router_py/streaming_voice.py`

## Environment Flags
- LUCY_ROUTER_PY=1 (Python router)
- LUCY_VOICE_PY=1 (Python voice)
- LUCY_LOCAL_ANSWER_PY=1 (Python local_answer)

## Architecture Notes

### Kokoro TTS Resolution (FIXED)
**Problem:** Kokoro is installed in ui-v8 venv but voice_tool.py runs in system Python.
Direct import fails because Kokoro is not in system Python's site-packages.

**Solution:** voice_tool.py always uses subprocess with ui-v8 Python for TTS synthesis.
The `_synthesize_with_subprocess()` method calls tts_adapter.py via subprocess,
avoiding Python environment issues.

**Key Code:**
```python
# In voice_tool.py::synthesize()
voice_python = self._resolve_voice_python()
if not voice_python:
    raise SynthesisError("No voice Python available. Ensure ui-v8 venv exists.")

result = self._synthesize_with_subprocess(
    text=text.strip(),
    engine=engine,
    voice=voice,
    output_dir=tmpdir,
    python_bin=voice_python,
)
```

**Socket Worker:** Kokoro is actually accessed via Unix socket at `tmp/run/kokoro_tts_worker.sock`.
The socket worker is started by streaming_voice.py and handles synthesis requests.

### Two-Python Environment Strategy
1. System Python runs: router, voice_tool, local_answer, execution_engine
2. UI-v8 Python provides: Kokoro TTS, other UI-specific packages
3. Communication via: Subprocess calls (tts_adapter.py CLI interface)

### Voice Tool Cleanup (Priority 3 - IMPLEMENTED)
**Status:** `lucy_voice_ptt.sh` (1,503 lines) is now DEPRECATED.

**Migration:**
- Old: `tools/lucy_voice_ptt.sh` (shell script)
- New: `tools/router_py/voice_runtime.py` (Python)

**Usage:**
```bash
# Use new Python voice runtime
export LUCY_VOICE_PY=1
./tools/start_local_lucy_opt_experimental_v7_dev.sh
# Then use /voice command

# Or suppress deprecation warning for old script
export LUCY_VOICE_PY_SILENCE_DEPRECATION=1
./tools/lucy_voice_ptt.sh
```

**Implementation Details:**
- `voice_runtime.py` provides interactive voice loop using `StreamingVoicePipeline`
- Uses streaming TTS for minimal latency
- Handles signals (Ctrl+C) gracefully
- Supports oneshot and continuous modes
- Respects LUCY_VOICE_ROUTE_MODE, LUCY_VOICE_ONESHOT, LUCY_VOICE_PTT_MODE

**Files Modified:**
- `tools/lucy_voice_ptt.sh` - Added deprecation warning (v8 only)
- `tools/router_py/voice_runtime.py` - NEW Python voice runtime
- `tools/start_v8_hmi_python.sh` - Sets LUCY_VOICE_PY=1

### First Half Second Missing - FIXED
**Problem:** When using streaming TTS, the first ~0.5 seconds of audio was being cut off.

**Root Cause:** The streaming pipeline was starting audio playback (aplay) BEFORE the first audio chunk was synthesized, causing a buffer underrun.

**Solution (streaming_voice.py):**
1. Synthesize the FIRST chunk BEFORE starting aplay
2. Add 120ms of silence prepad before the first chunk to ensure audio system is ready
3. Then start playback with buffered audio

**Code Change:**
```python
# OLD: Start aplay immediately, then synthesize (causes gap)
aplay_proc = await asyncio.create_subprocess_exec(...)
for phrase in phrases:
    audio_data = await self._synthesize_to_pcm(phrase)
    aplay_proc.stdin.write(audio_data)

# NEW: Buffer first chunk, add prepad, then start playback
first_chunk_pcm = await self._synthesize_to_pcm(phrases[0])
prepad_silence = struct.pack(f'<{silence_samples}h', *([0] * silence_samples))

aplay_proc = await asyncio.create_subprocess_exec(...)
aplay_proc.stdin.write(prepad_silence)  # 120ms silence
aplay_proc.stdin.write(first_chunk_pcm)  # First chunk (already ready)
await aplay_proc.stdin.drain()

# Continue with remaining phrases...
```

**Result:** First chunk is fully synthesized and ready before playback starts, eliminating the cut-off.

### Voice Selection - UPDATED
**Default Voice Changed:** af_heart → af_nicole

**Why:** af_nicole provides a soft, gentle, and very natural American female voice.

**Available Voices:**
- af_nicole (DEFAULT) - American female, soft and gentle ⭐
- af_bella - American female, clear and professional ⭐
- am_adam - American male, deep and natural ⭐
- af_heart - American female, warm (original default)
- bf_emma - British female, natural
- bm_george - British male, professional

**Change Voice:**
```bash
export LUCY_VOICE_KOKORO_VOICE=af_nicole
./start_v8_hmi_python.sh
```

**Files Modified:**
- `tools/voice/backends/kokoro_backend.py` - default voice
- `tools/router_py/streaming_tts_helper.py` - default voice
- `tools/router_py/streaming_voice.py` - voice parameter support
