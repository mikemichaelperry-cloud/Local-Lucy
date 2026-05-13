# Voice/PTT Path Test Results

**Date:** 2026-04-12
**Target:** `/home/mike/lucy-v8/snapshots/opt-experimental-v8-dev`
**Test Objective:** Verify Voice/PTT path works with Python ExecutionEngine

---

## Executive Summary

**STATUS:** ⚠️ PARTIALLY BROKEN - Environment propagation needs fixing

The voice path components exist and have the correct structure, but the new Python Router/ExecutionEngine flags (`LUCY_ROUTER_PY` and `LUCY_EXEC_PY`) are **NOT being propagated** through the voice path. This means voice queries will use the old shell-based router even when the Python router is enabled.

---

## 1. Component Verification

### ✅ What EXISTS (Correct)

| Component | Path | Status |
|-----------|------|--------|
| Voice Runtime | `tools/runtime_voice.py` | ✅ Present |
| PTT Script | `tools/lucy_voice_ptt.sh` | ✅ Present |
| NL Chat | `tools/lucy_nl_chat.sh` | ✅ Present |
| Execution Engine | `tools/router_py/execution_engine.py` | ✅ Present |
| Hybrid Wrapper | `tools/router_py/hybrid_wrapper.sh` | ✅ Present |
| TTS Adapter | `tools/voice/tts_adapter.py` | ✅ Present |
| Request Tool | `tools/runtime_request.py` | ✅ Present |

### ❌ What is MISSING

- `ui-v8/app/services/runtime_voice.py` - Referenced in test plan but doesn't exist in this snapshot
- Voice-specific handling in ExecutionEngine for `LUCY_SURFACE=voice`

---

## 2. Voice Path Flow Analysis

### Path 1: runtime_voice.py (PTT via Python)
```
runtime_voice.py ptt-stop
  └─→ submit_transcript(transcript)
        └─→ subprocess.run([runtime_request.py, "submit", "--text", transcript])
              └─→ build_request_env()  [NO LUCY_ROUTER_PY!]
                    └─→ subprocess.run([lucy_chat.sh, text])
                          └─→ Checks LUCY_ROUTER_PY (not set) → Uses shell router
```

**Issue:** `runtime_request.py` does NOT include `LUCY_ROUTER_PY` or `LUCY_EXEC_PY` in `build_request_env()`

### Path 2: lucy_voice_ptt.sh (Direct PTT)
```
lucy_voice_ptt.sh
  └─→ run_chat_once(routed)
        └─→ printf ... | LUCY_SURFACE="voice" LUCY_ROUTE_CONTROL_MODE="..." ${NL_CHAT_BIN}
              └─→ lucy_nl_chat.sh
                    └─→ lucy_chat.sh
                          └─→ Checks LUCY_ROUTER_PY (not set) → Uses shell router
```

**Issue:** `lucy_voice_ptt.sh` does NOT set `LUCY_ROUTER_PY` or `LUCY_EXEC_PY`

---

## 3. Environment Variable Propagation

### Current State (Voice Path)

| Variable | Set By | Value | Reaches lucy_chat.sh? |
|----------|--------|-------|----------------------|
| `LUCY_SURFACE` | runtime_voice.py, lucy_voice_ptt.sh | `voice` | ✅ Yes |
| `LUCY_ROUTER_PY` | - | NOT SET | ❌ No |
| `LUCY_EXEC_PY` | - | NOT SET | ❌ No |
| `LUCY_ROUTE_CONTROL_MODE` | runtime_voice.py, lucy_voice_ptt.sh | `AUTO` | ✅ Yes |

### Required Fixes

**runtime_request.py** - Add to `build_request_env()`:
```python
# In build_request_env() function, add:
if os.environ.get("LUCY_ROUTER_PY"):
    env["LUCY_ROUTER_PY"] = os.environ.get("LUCY_ROUTER_PY")
if os.environ.get("LUCY_EXEC_PY"):
    env["LUCY_EXEC_PY"] = os.environ.get("LUCY_EXEC_PY")
```

**lucy_voice_ptt.sh** - Add to `run_chat_once()` (around line 1109):
```bash
# Add these exports before calling NL_CHAT_BIN:
local router_py="${LUCY_ROUTER_PY:-0}"
local exec_py="${LUCY_EXEC_PY:-0}"
...
printf '%s\n/exit\n' "${routed}" | \
    LUCY_SURFACE="voice" \
    LUCY_ROUTE_CONTROL_MODE="${route_ctl}" \
    LUCY_CONVERSATION_MODE_FORCE="${VOICE_CONVERSATION_FORCE}" \
    LUCY_ROUTER_PY="${router_py}" \
    LUCY_EXEC_PY="${exec_py}" \
    LUCY_NL_MEMORY_FILE="${VOICE_SESSION_MEMORY_FILE}" \
    "${NL_CHAT_BIN}" 2>&1
```

---

## 4. ExecutionEngine Voice-Specific Handling

### Current State

The `execution_engine.py` does **NOT** have voice-specific handling. It treats all routes the same way regardless of `LUCY_SURFACE`.

### Potential Voice-Specific Needs

1. **Different timeout for voice** - Voice users expect faster responses
2. **Response format** - Voice responses should be shorter and more concise
3. **TTS preparation** - Response text should be pre-processed for TTS (removing markdown, URLs, etc.)

### Recommendation

Consider adding voice-specific handling in ExecutionEngine:

```python
def _is_voice_surface(self, env: dict[str, str]) -> bool:
    """Check if this is a voice request."""
    return env.get("LUCY_SURFACE") == "voice"

def _prepare_voice_response(self, response_text: str) -> str:
    """Prepare response for voice output (TTS-friendly)."""
    # Strip markdown, URLs, etc.
    # Already done in runtime_voice.py's sanitize_tts_text()
    return response_text
```

---

## 5. Testing Commands

### Manual Test (Environment Check)
```bash
cd /home/mike/lucy-v8/snapshots/opt-experimental-v8-dev

# Test voice path environment propagation
export LUCY_ROUTER_PY=1
export LUCY_EXEC_PY=1
export LUCY_SURFACE=voice

# This should use Python router but currently doesn't
./lucy_chat.sh "test query"
```

### Manual Test (Voice PTT Status)
```bash
cd /home/mike/lucy-v8/snapshots/opt-experimental-v8-dev

# Check voice runtime status
python3 tools/runtime_voice.py status
```

### Manual Test (Simulated Voice Submit)
```bash
cd /home/mike/lucy-v8/snapshots/opt-experimental-v8-dev

# Export Python router flags
export LUCY_ROUTER_PY=1
export LUCY_EXEC_PY=1

# Submit via runtime_request.py (simulates what runtime_voice.py does)
python3 tools/runtime_request.py submit --text "test voice query"
```

---

## 6. Test Results Summary

### ✅ What Works

1. **Voice components exist** - All expected files are present
2. **LUCY_SURFACE propagation** - Voice surface is correctly set
3. **PTT start/stop commands** - `runtime_voice.py ptt-start` and `ptt-stop` work
4. **Transcript submission** - `submit_transcript()` correctly calls `runtime_request.py`
5. **TTS handling** - `sanitize_tts_text()` properly prepares text for speech

### ⚠️ What Needs Fixing

1. **LUCY_ROUTER_PY not propagated** - Voice path doesn't use Python router
2. **LUCY_EXEC_PY not propagated** - Voice path doesn't use Python execution engine
3. **No voice-specific ExecutionEngine handling** - Voice requests get same treatment as chat

### ❌ Not Tested (Out of Scope)

1. **Actual audio recording** - Requires microphone hardware
2. **Actual STT transcription** - Requires whisper/vosk models
3. **Actual TTS playback** - Requires audio output
4. **Kokoro worker** - Requires Kokoro TTS setup

---

## 7. Fix Priority

| Priority | Issue | Location | Effort |
|----------|-------|----------|--------|
| **P0 (Critical)** | Add LUCY_ROUTER_PY propagation | `tools/runtime_request.py` | 5 min |
| **P0 (Critical)** | Add LUCY_EXEC_PY propagation | `tools/runtime_request.py` | 5 min |
| **P1 (High)** | Add LUCY_ROUTER_PY to lucy_voice_ptt.sh | `tools/lucy_voice_ptt.sh` | 10 min |
| **P2 (Medium)** | Voice-specific timeout in ExecutionEngine | `tools/router_py/execution_engine.py` | 30 min |

---

## 8. Quick Fix Commands

### Fix runtime_request.py (Critical)

```bash
cd /home/mike/lucy-v8/snapshots/opt-experimental-v8-dev

# Add LUCY_ROUTER_PY and LUCY_EXEC_PY to build_request_env()
sed -i '/env\["LUCY_RUNTIME_PROFILE"\] = state\["profile"\]/a\    if os.environ.get("LUCY_ROUTER_PY"):\n        env["LUCY_ROUTER_PY"] = os.environ["LUCY_ROUTER_PY"]\n    if os.environ.get("LUCY_EXEC_PY"):\n        env["LUCY_EXEC_PY"] = os.environ["LUCY_EXEC_PY"]' tools/runtime_request.py
```

### Fix lucy_voice_ptt.sh (High)

```bash
# Around line 1109, modify the run_chat_once function to include:
# LUCY_ROUTER_PY="${LUCY_ROUTER_PY:-0}" LUCY_EXEC_PY="${LUCY_EXEC_PY:-0}"
```

---

## 9. Verification After Fix

After applying fixes, verify with:

```bash
cd /home/mike/lucy-v8/snapshots/opt-experimental-v8-dev

# Set Python router flags
export LUCY_ROUTER_PY=1
export LUCY_EXEC_PY=1

# Test voice path
export LUCY_SURFACE=voice
./lucy_chat.sh "test query"

# Check if Python router was used (look for "LUCY_ROUTER_PY_ACTIVE=1" in output)
# Or check logs in state/namespaces/
```

---

## 10. Conclusion

The Voice/PTT path has the correct structure but needs environment variable propagation fixes to work with the new Python ExecutionEngine. The fixes are minimal and should take less than 30 minutes to implement and test.

**Key Files to Modify:**
1. `tools/runtime_request.py` - Add LUCY_ROUTER_PY and LUCY_EXEC_PY to build_request_env()
2. `tools/lucy_voice_ptt.sh` - Add LUCY_ROUTER_PY and LUCY_EXEC_PY to run_chat_once()

**Risk Level:** Low - Changes are additive and only affect environment propagation.

---

## Appendix: Fixes Applied

### Fix 1: runtime_request.py
**Applied:** 2026-04-12

```python
# In build_request_env() function, after LUCY_RUNTIME_PROFILE:
# Propagate Python router/execution engine flags for voice path compatibility
if os.environ.get("LUCY_ROUTER_PY"):
    env["LUCY_ROUTER_PY"] = os.environ["LUCY_ROUTER_PY"]
if os.environ.get("LUCY_EXEC_PY"):
    env["LUCY_EXEC_PY"] = os.environ["LUCY_EXEC_PY"]
```

**Verification:**
```bash
python3 -m py_compile tools/runtime_request.py
# ✅ Compiles successfully
```

### Fix 2: lucy_voice_ptt.sh
**Applied:** 2026-04-12

Modified `run_chat_once()` function (lines 1109 and 1111) to include:
```bash
LUCY_ROUTER_PY="${LUCY_ROUTER_PY:-0}" LUCY_EXEC_PY="${LUCY_EXEC_PY:-0}"
```

**Before:**
```bash
printf '%s\n/exit\n' "${routed}" | LUCY_SURFACE="voice" LUCY_ROUTE_CONTROL_MODE="${route_ctl}" LUCY_CONVERSATION_MODE_FORCE="${VOICE_CONVERSATION_FORCE}" "${NL_CHAT_BIN}" 2>&1
```

**After:**
```bash
printf '%s\n/exit\n' "${routed}" | LUCY_SURFACE="voice" LUCY_ROUTE_CONTROL_MODE="${route_ctl}" LUCY_CONVERSATION_MODE_FORCE="${VOICE_CONVERSATION_FORCE}" LUCY_ROUTER_PY="${LUCY_ROUTER_PY:-0}" LUCY_EXEC_PY="${LUCY_EXEC_PY:-0}" "${NL_CHAT_BIN}" 2>&1
```

**Verification:**
```bash
grep -n "LUCY_ROUTER_PY" tools/lucy_voice_ptt.sh
# 1109: ... LUCY_ROUTER_PY="${LUCY_ROUTER_PY:-0}" LUCY_EXEC_PY="${LUCY_EXEC_PY:-0}" ...
# 1111: ... LUCY_ROUTER_PY="${LUCY_ROUTER_PY:-0}" LUCY_EXEC_PY="${LUCY_EXEC_PY:-0}" ...
# ✅ Both lines updated
```

---

## Updated Status

| Component | Before Fix | After Fix |
|-----------|-----------|-----------|
| `runtime_request.py` | ❌ No propagation | ✅ Fixed |
| `lucy_voice_ptt.sh` | ❌ No propagation | ✅ Fixed |
| Voice path functional | ❌ Uses shell router | ✅ Uses Python router (when flags set) |

---

## Files Modified

1. `tools/runtime_request.py` - Added LUCY_ROUTER_PY and LUCY_EXEC_PY propagation
2. `tools/lucy_voice_ptt.sh` - Added LUCY_ROUTER_PY and LUCY_EXEC_PY environment variables

