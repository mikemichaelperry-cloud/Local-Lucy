# LLV8 Session Handoff - 2026-04-16

**Session Date**: 2026-04-16  
**Status**: Voice Pipeline & Routing Fixes  
**Next Priority**: Voice Cutoff Testing, Medical Query Execution Bug

---

## ✅ COMPLETED TODAY

### 1. Policy Enforcement Bug Fix (CRITICAL)
**Issue**: Evidence mode queries bypassed augmentation policy check  
**Root Cause**: `evidence_mode` check happened before `policy` check in classify.py  
**Fix**: Moved `policy == "disabled"` check to occur before `evidence_mode` check

**Files Modified**:
- `tools/router_py/classify.py` (lines 214-220)

**Test Results**: 7/7 tests passing

---

### 2. Time Query Detection (AUTO Mode Improvement)
**Issue**: "What time is it in London?" stayed offline (incorrect)  
**Root Cause**: No regex pattern for time-of-day queries  
**Fix**: Added `TIME_QUERY_PATTERN` and `is_time_query()` function

**Files Modified**:
- `tools/router/core/routing_signals.py` - Added time query patterns
- `tools/router/core/intent_classifier.py` - Added time query classification

**Test Results**: AUTO mode accuracy improved from 86% → 100% (14/14 tests)

---

### 3. Voice Pipeline Fixes
**Issues Addressed**:
1. Voice cutting off before all text spoken
2. High latency from subprocess fallback
3. Sources being spoken (should be display-only)
4. News content truncated (240 char limit)

**Changes Made**:

#### `tools/router_py/streaming_voice.py`
- Removed 4000 char TTS text limit
- Increased trailing silence: 500ms → 2000ms
- Increased wait time before closing aplay: 0.5s → 2.5s
- Added sample rate conversion for worker socket (24kHz → 22050 Hz)
- Added larger aplay buffer: `--buffer-size=65536`
- Removed sources from TTS output (display-only now)
- Installed numpy for resampling support

#### `tools/router_py/local_answer.py`
- Increased token limits for augmented responses:
  - `num_predict_augmented_default`: 32 → 128
  - `num_predict_augmented_detail`: 56 → 512
  - `num_predict_detail`: 384 → 768

#### `tools/build_news_digest.sh`
- Increased description truncation: 240 → 600 characters

---

## ⚠️ KNOWN ISSUES (Not Fixed)

### Critical
1. **Voice Still Cutting Off**
   - Despite multiple fixes (trailing silence, wait times, buffer sizes)
   - May need aplay alternative (paplay/pw-play) or different audio backend
   - Could be hardware buffer underrun on specific systems

2. **Medical Query Execution Bug**
   - Query: "Does taking supplemental magnesium help with heart arrhythmia?"
   - Routing: Correct (MEDICAL_INFO → medical_runtime.txt)
   - Execution: Returns news headlines instead of medical evidence
   - Location: Shell execution layer (execute_plan.sh / evidence tools)

### Medium
3. **News Content Still Truncated at Source**
   - Some truncation happens before build_news_digest.sh
   - May be in fetch_evidence.sh or evidence pack building

---

## 📊 CURRENT STATE

### Test Coverage
| Component | Tests | Passed | Status |
|-----------|-------|--------|--------|
| Policy enforcement | 7 | 7 | ✅ 100% |
| Time queries | 10 | 10 | ✅ 100% |
| AUTO mode routing | 14 | 14 | ✅ 100% |
| HMI toggles | 50 | 50 | ✅ 100% |
| Router core | 17 | 17 | ✅ 100% |

### Active Configuration
```json
{
  "mode": "auto",
  "voice": "on",
  "evidence": "on",
  "memory": "off",
  "conversation": "on",
  "augmentation_policy": "direct_allowed",
  "voice": "af_bella",
  "numpy": "installed (2.2.6)"
}
```

---

## 🎯 NEXT SESSION PRIORITIES

### Option 1: Voice Cutoff Fix (Testing Required)
**Effort**: 30-60 minutes  
**Impact**: High (if testing reveals solution)

Test approaches:
- Try `paplay` instead of `aplay` (PulseAudio)
- Try `pw-play` instead of `aplay` (PipeWire)
- Add `--period-size` parameter to aplay
- Test with smaller buffer sizes
- Check for system audio buffer settings

### Option 2: Medical Query Execution Bug
**Effort**: 2-4 hours  
**Impact**: High (affects medical evidence reliability)

Investigate:
- `tools/evidence_answer.sh` execution path
- `tools/internet/dispatch_tool.sh` domain filtering
- Medical runtime allowlist enforcement

### Option 3: Router Core Migration (Big Task)
**Effort**: 4-8 hours  
**Impact**: Very High (removes 3,899 lines of shell)

Continue migration of `execute_plan.sh` → `execution_engine.py`

---

## 🔧 QUICK COMMANDS FOR NEXT SESSION

### Test Voice
```bash
cd ~/lucy-v8/snapshots/opt-experimental-v8-dev
python3 tools/voice/tts_adapter.py synthesize "Test message for voice"
```

### Test Time Query
```bash
python3 -c "
import sys
sys.path.insert(0, 'tools')
from router_py.classify import classify_intent, select_route
c = classify_intent('What time is it in London?')
d = select_route(c, policy='direct_allowed')
print(f'Route: {d.route}')
"
```

### Test Policy Fix
```bash
python3 tools/tests/test_policy_enforcement_bug.py
```

### Clear Python Cache
```bash
rm -rf ~/lucy-v8/snapshots/opt-experimental-v8-dev/tools/router_py/__pycache__
```

### Check Voice Debug Output
```bash
# Look for [TTS Debug] messages in terminal output
```

---

## 📁 FILES REFERENCE

### Test Files
- `tools/tests/test_policy_enforcement_bug.py` - Policy fix tests
- `tools/tests/test_time_queries.py` - Time query tests
- `tools/tests/test_auto_mode.py` - AUTO mode routing tests

### Core Modified Files
- `tools/router_py/classify.py` - Policy enforcement fix
- `tools/router_py/streaming_voice.py` - Voice pipeline fixes
- `tools/router_py/local_answer.py` - Token limit increases
- `tools/router/core/routing_signals.py` - Time query patterns
- `tools/router/core/intent_classifier.py` - Time query classification
- `tools/build_news_digest.sh` - Description length limit

### Shell Files (Still Buggy)
- `tools/evidence_answer.sh` - Medical query returns news
- `tools/internet/dispatch_tool.sh` - May not enforce domain filters

---

## 🐛 DEBUGGING TIPS

### If Voice Still Cuts Off
1. Check `[TTS Debug]` output for phrase count
2. Try alternative audio player in `streaming_voice.py`:
   - Replace `"aplay"` with `"paplay"` (PulseAudio)
   - Replace `"aplay"` with `"pw-play"` (PipeWire)
3. Check system audio: `pactl info` or `wpctl status`
4. Test audio directly: `aplay -t raw -f S16_LE -r 22050 test.pcm`

### If Medical Query Returns News
1. Check `tools/router_py/classify.py` correctly routes to MEDICAL_INFO
2. Check `medical_runtime.txt` exists and has valid domains
3. Check evidence tool respects `allow_domains_file`

---

## 🎯 STABILITY CRITERIA UPDATE

Before considering model upgrade:
- [ ] Voice pipeline stable (no cutoffs) for 20+ queries
- [ ] Medical queries return medical evidence (not news)
- [ ] 48-hour soak test without crashes
- [ ] All toggles working correctly in production use

---

## NOTES

- Hardware: RTX 3060 12GB VRAM
- Current model: local-lucy 7B (~4.9 GB)
- Voice: Kokoro TTS (af_bella) + Whisper STT
- Numpy: Now installed (required for audio resampling)
- State DB: SQLite at `~/.codex-api-home/lucy/runtime-v8/state/lucy_state.db`

---

**Prepared for**: Next session continuation  
**Prepared by**: Kimi Code CLI  
**Date**: 2026-04-16
