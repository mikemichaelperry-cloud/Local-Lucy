# Stage 0 — Discovery & Baseline

## Baseline (2026-05-10)
- Commit: `5cf9010cfa02e02a79491ae83a1149c8a03b891a`
- Tests: 179 passed, 19 skipped, 0 failed
- Files modified in working tree: 42

## Entry Points

### 1. HMI bridge (`ui-v9/app/services/runtime_bridge.py`)
- Path: `_run_submit_request_direct()` → `main.run()` ✅ (already unified)
- No longer instantiates ExecutionEngine directly
- Still has `_resolve_augmented_provider()` which duplicates `main.py`'s `ensure_control_env()`

### 2. CLI (`tools/router_py/main.py`)
- Path: `main()` → `execute_plan_python()` → `ExecutionEngine`
- `run()` is the unified entry point

### 3. Voice streaming (`tools/router_py/streaming_voice.py`)
- Path: `_get_full_response()` → direct `ExecutionEngine` + `classify_intent/select_route`
- BYPASSES `main.run()` — this is a leak

### 4. Voice tool (`tools/router_py/voice_tool.py`)
- Path: tries `execute_plan_python()` first, falls back to direct `ExecutionEngine`
- Fallback BYPASSES `main.run()` — this is a leak

### 5. Runtime voice (`tools/runtime_voice.py`)
- Path: `submit_transcript()` → direct `ExecutionEngine` + `classify_intent/select_route`
- BYPASSES `main.run()` — this is a leak

## ExecutionEngine Direct Instantiations
| File | Line | Notes |
|------|------|-------|
| `main.py` | 793 | Unified path ✅ |
| `streaming_voice.py` | 515 | Voice bypass ❌ |
| `voice_tool.py` | 867 | Voice fallback ❌ |
| `runtime_voice.py` | 1612 | Voice bypass ❌ |
| `thrash_v8.py` | 86 | Test only |
| `burn_in_test.py` | 245 | Test only |

## Provider Selection Smear
1. `classify.py` `_resolve_provider_preference()` checks `LUCY_AUGMENTED_PROVIDER` env var → sets in `RoutingDecision`
2. `main.py` passes `augmented_provider` in context to `ExecutionEngine`
3. `execution_engine.py` `_execute_full_route_python()` reads context and overrides `route.provider` via `dataclasses.replace()`
4. `execution_engine.py` `_call_augmented_provider()` also checks `context["augmented_provider"]` for provider chain

Two layers are making provider decisions. Need to centralize.

## Memory Flow
1. `classify.py` `_memory_routing_gate()` — pre-routing gate, overrides live-data routes for follow-ups
2. `execution_engine.py` `_load_session_memory_context_with_telemetry()` — loads memory during execution
3. `execution_engine.py` — stores turns via `store_turn()` after execution
4. `main.py` — also stores turns (dual-write, legacy text file)

Memory is loaded and stored in two places.

## execution_engine.py Monolith
- 3,965 lines
- Contains: routing dispatch, evidence fetching, provider calls, local worker calls, memory loading, prompt building, response validation, response formatting, subprocess management, telemetry, state file writing

## Key Design Preservations
- `_memory_routing_gate()` is well-designed, reusable
- `RoutingDecision` is `@dataclass(frozen=True)`
- Feedback parser in `main.py` returns early (good)
- `ensure_control_env()` reads state file (good, but duplicated)
