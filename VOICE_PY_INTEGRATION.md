# Voice Python Pipeline Integration (V8)

## Summary

This document describes the integration of the Python-native voice pipeline (`voice_tool.py`) with the shell-based `runtime_voice.py` and HMI.

## Architecture

```
HMI (ui-v8)
    ↓
RuntimeBridge (runtime_bridge.py)
    ↓
runtime_voice.py (shell entry point)
    ├── Shell path (default)
    └── Python path (when LUCY_VOICE_PY=1)
            ↓
    voice_tool.py (Python-native pipeline)
```

## Components

### 1. voice_tool.py (`tools/router_py/voice_tool.py`)

A comprehensive async voice pipeline providing:
- Audio recording (arecord/pw-record)
- Voice Activity Detection (VAD)
- Transcription (Whisper)
- Lucy request processing
- TTS synthesis (Kokoro/Piper)
- Audio playback
- Full cancellation support
- Metrics collection

Key classes:
- `VoicePipeline`: Main orchestration class
- `VoiceResult`: Result data class
- `AudioBuffer`: Audio data container
- `VoiceMetrics`: Performance metrics

### 2. runtime_voice.py (`tools/runtime_voice.py`)

Modified to support dual-mode operation:
- Shell-based voice (default)
- Python-based voice (when `LUCY_VOICE_PY=1`)

New functions added:
- `use_python_voice()`: Check toggle
- `handle_status_python()`: Status via Python
- `handle_ptt_start_python()`: PTT start via Python
- `handle_ptt_stop_python()`: PTT stop via Python

### 3. runtime_bridge.py (`ui-v8/app/services/runtime_bridge.py`)

Modified to propagate `LUCY_VOICE_PY` environment variable to voice subprocesses.

## Usage

### Enable Python Voice Pipeline

```bash
export LUCY_VOICE_PY=1
```

Or set in the HMI environment.

### Direct Python API

```python
from router_py.voice_tool import VoicePipeline

pipeline = VoicePipeline()

# Full interaction
result = await pipeline.voice_interaction(
    on_transcription=lambda text: print(f"You said: {text}"),
    on_response=lambda text: print(f"Lucy said: {text}"),
)

print(f"Success: {result.success}")
print(f"Transcript: {result.transcript}")
print(f"Response: {result.response_text}")
```

### Shell Commands (Backward Compatible)

```bash
# Status
python3 tools/runtime_voice.py status

# PTT Start
python3 tools/runtime_voice.py ptt-start

# PTT Stop
python3 tools/runtime_voice.py ptt-stop
```

With Python voice enabled:
```bash
LUCY_VOICE_PY=1 python3 tools/runtime_voice.py status
```

### Health Check

```bash
cd tools/router_py
python3 voice_tool.py --test health
```

## Testing

### Run Health Check
```bash
cd /home/mike/lucy-v8/snapshots/opt-experimental-v8-dev
cd tools/router_py
python3 voice_tool.py --test health
```

### Test with Runtime
```bash
cd /home/mike/lucy-v8/snapshots/opt-experimental-v8-dev
export LUCY_RUNTIME_AUTHORITY_ROOT=/home/mike/lucy-v8/snapshots/opt-experimental-v8-dev
export LUCY_UI_ROOT=/home/mike/lucy-v8/ui-v8
export LUCY_RUNTIME_NAMESPACE_ROOT=/home/mike/.codex-api-home/lucy/runtime-v7

# Shell mode (default)
python3 tools/runtime_voice.py status

# Python mode
LUCY_VOICE_PY=1 python3 tools/runtime_voice.py status
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `LUCY_VOICE_PY` | Enable Python voice pipeline | `0` (disabled) |
| `LUCY_VOICE_PYTHON_BIN` | Python binary for voice operations | auto-detected |
| `LUCY_VOICE_WHISPER_MODEL` | Whisper model path | auto-detected |
| `LUCY_VOICE_STT_LANG` | STT language | `auto` |
| `LUCY_VOICE_TTS_ENGINE` | TTS engine (kokoro/piper) | `auto` |
| `LUCY_VOICE_TTS_MAX_CHARS` | Max TTS characters | `2000` |
| `LUCY_VOICE_TTS_CHUNK_PAUSE_MS` | Pause between chunks | `56` |

## Backward Compatibility

The integration maintains full backward compatibility:
- Default behavior unchanged (shell-based)
- Toggle required to enable Python voice (`LUCY_VOICE_PY=1`)
- All existing environment variables respected
- Shell commands work identically

## Error Handling

Both paths include proper error handling:
1. Python path errors fall back to shell path
2. Shell path errors return proper exit codes
3. HMI receives consistent error messages

## Performance Considerations

- Python voice pipeline uses async I/O for lower latency
- VAD reduces unnecessary transcription
- TTS prewarming available for Kokoro
- Metrics collection for performance monitoring

## Future Enhancements

Potential improvements:
1. Streaming transcription for real-time feedback
2. Wake word detection
3. Conversation context preservation
4. Voice activity visualization
5. Adaptive noise filtering

## Files Modified

1. `tools/runtime_voice.py` - Added Python voice integration
2. `tools/router_py/__init__.py` - Added voice tool exports
3. `ui-v8/app/services/runtime_bridge.py` - Added LUCY_VOICE_PY propagation

## Files Added

1. `tools/router_py/voice_tool.py` - Python voice pipeline (already existed, integrated)
2. `tools/router_py/test_voice_tool.py` - Unit tests for voice tool
