# Phase 8c Completion Report — Split `tools/router_py/voice_tool.py`

**Date:** 2026-07-27  
**Branch:** `phase8-voice-tool-split` (HEAD `4867b58`, ahead of `main` at `aed90f6`)  
**Scope:** `tools/router_py/voice_tool.py` → `tools/router_py/voice/` package  
**V10 preservation:** The `lucy-v10/` tree is untouched; this refactor applies only to V11 (`lucy-v11/`).

## Objective

Split the monolithic `tools/router_py/voice_tool.py` into a focused `tools/router_py/voice/` package and migrate all callers, preserving behavior.

## Changes

### New files

| File | Purpose |
|------|---------|
| `tools/router_py/voice/__init__.py` | Public re-exports; heavy `pipeline` import is optional with placeholders |
| `tools/router_py/voice/exceptions.py` | `VoicePipelineError`, `RecordingError`, `TranscriptionError`, `SynthesisError`, `PlaybackError` |
| `tools/router_py/voice/models.py` | `AudioBuffer`, `TranscriptionResult`, `VADConfig`, `VoiceMetrics`, `VoiceResult` |
| `tools/router_py/voice/utils.py` | `clean_text`, `iso_now`, `_voice_usage_logger` |
| `tools/router_py/voice/pipeline.py` | `VoicePipeline`, `quick_voice_interaction` |
| `tools/router_py/test_voice_tool_characterization.py` | Characterization tests for the public API |

### Deleted file

- `tools/router_py/voice_tool.py`

### Callers migrated

- `tools/router_py/__init__.py`
- `tools/router_py/streaming_voice.py`
- `tools/router_py/voice_runtime.py`
- `tools/router_py/test_voice_tool.py`
- `tools/router_py/test_voice_tool_characterization.py`
- `tools/router_py/test_request_pipeline_contract.py`
- `tools/runtime_voice.py`
- `ui-v10/app/backend/__init__.py`
- `ui-v10/app/backend/streaming_voice.py`
- `ui-v10/app/backend/voice.py`
- `ui-v10/app/backend/voice_tool.py`

All runtime imports now use `from router_py.voice import ...`.

### Remaining references

```bash
grep -R "from router_py\.voice_tool\|import router_py\.voice_tool\|from voice_tool import\|import voice_tool" \
  --include="*.py" tools/ ui-v10/
```

Result: `No non-sensitive matches found`

## Verification

### Lint

```bash
python3 -m ruff check tools/router_py/voice/ tools/router_py/streaming_voice.py \
  tools/router_py/voice_runtime.py tools/router_py/__init__.py tools/runtime_voice.py \
  ui-v10/app/backend/__init__.py ui-v10/app/backend/streaming_voice.py \
  ui-v10/app/backend/voice.py ui-v10/app/backend/voice_tool.py
```

Result: `All checks passed!`

### Characterization tests

```bash
python3 -m pytest tools/router_py/test_voice_tool_characterization.py -q --tb=line
```

Result: `8 passed in 0.04s`

### Fast router suite

```bash
./scripts/run-fast-tests.sh
```

Result: `701 passed, 7 skipped, 261 deselected, 169 subtests passed in 109.45s`

## Gate assessment

| Gate | Status | Evidence |
|------|--------|----------|
| Behavior preserved | ✅ | Characterization tests pass; public API symbols unchanged |
| Callers migrated | ✅ | Grep shows no remaining `voice_tool` imports in `.py` files |
| Old module removed | ✅ | `tools/router_py/voice_tool.py` deleted and committed |
| Lint clean | ✅ | `ruff check` passes on all touched files |
| Fast suite passes | ✅ | 701 passed, no regressions |
| Scope respected | ✅ | Only `voice_tool.py`, new `voice/` package, and direct callers touched |

## Notes

- `PlaybackError` was being shadowed in `voice/pipeline.py` because the file imported `PlaybackError` from `playback` (a plain `RuntimeError`) and then re-imported `PlaybackError` from `router_py.voice.exceptions`. The `playback` symbol was dropped so only the exceptions-module class is used, matching the original module's final binding.
- `voice/__init__.py` imports core symbols unconditionally and defers the heavy `pipeline` module inside a `try/except`, providing placeholder `VoicePipeline`/`quick_voice_interaction` when voice dependencies are missing.
- The split follows the same pattern as `state_manager.py` and `news_provider.py`: characterization tests → package → migrate callers → delete old file.
- A note for a future deeper review: Ollama still held ~60% VRAM after live news tests. The voice system itself was not live-tested during this refactor beyond the fast test suite; a more thorough review of voice resource handling may be warranted before heavy voice use.

## Next steps

Continue Phase 8 with the next module split. Recommended order:
1. `tools/router_py/policy.py`
2. `tools/router_py/policy_router.py`
3. `tools/router_py/local_answer.py`
4. `tools/router_py/execution_engine.py`
5. `tools/router_py/classify.py` (last — highest risk)
