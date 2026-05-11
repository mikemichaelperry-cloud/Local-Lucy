# Local Lucy v8 Router — Architecture

**Status:** Stages 0–9 complete. Python-native path is authoritative.

## Pipeline Flow

```
┌─────────────────┐    ┌──────────────┐    ┌───────────────┐    ┌───────────────┐    ┌─────────────┐
│   Entry Point   │───→│  Classify    │───→│    Route      │───→│   Execute     │───→│   Outcome   │
│   (run())       │    │  (intent)    │    │  (policy)     │    │  (engine)     │    │ (persist)   │
└─────────────────┘    └──────────────┘    └───────────────┘    └───────────────┘    └─────────────┘
        │                     │                   │                    │                   │
   feedback detect      Classification      RoutingDecision       ExecutionResult     RouterOutcome
   prefix parsing       Result            (+ provider_resolver)   (+ response_formatter)  (+ memory)
   ensure_control_env
```

## Modules

| File | Lines | Responsibility |
|------|-------|----------------|
| `main.py` | ~500 | Entry point. Feedback, locks, telemetry, memory persistence. Thin wrapper around `request_pipeline.process()`. |
| `request_pipeline.py` | ~300 | Pipeline choke point: classify → route → resolve provider → execute → convert result. |
| `request_types.py` | ~300 | Centralized dataclasses: `ClassificationResult`, `RoutingDecision`, `ExecutionResult`, `RouterOutcome`, `PipelineContext`. |
| `provider_resolver.py` | ~120 | Single source of truth for provider selection. Medical safety → context preference → env var → query-type default. |
| `response_formatter.py` | ~175 | Pure formatting/validation utilities: `validate_response`, `render_chat_fast_from_raw`, `build_augmented_prompt`, `guard_normalize`. |
| `classify.py` | ~850 | Intent classification (`classify_intent`), route selection (`select_route`), memory routing gate. |
| `execution_engine.py` | ~3,700 | Route dispatch, evidence fetching, provider calls, local worker calls, state file writing. |
| `providers/` | 8 files | Extracted provider modules: wikipedia, openai, kimi, weather, time, news, evidence, local. |

## Entry Points (all go through `main.run()`)

| Surface | File | Function | Calls |
|---------|------|----------|-------|
| CLI | `main.py` | `main()` | `run()` |
| HMI | `runtime_bridge.py` | `_run_submit_request_direct()` | `run()` |
| Voice (stream) | `streaming_voice.py` | `_get_full_response()` | `run()` via ThreadPoolExecutor |
| Voice (tool) | `voice_tool.py` | `process_query()` | `run()` via ThreadPoolExecutor |
| Voice (runtime) | `runtime_voice.py` | `submit_transcript()` | `run()` |

## State Propagation

| Variable | Read at | Written by | Purpose |
|----------|---------|------------|---------|
| `LUCY_SESSION_MEMORY` | classify, main | `current_state.json` | Enable memory gate + persistence |
| `LUCY_AUGMENTATION_POLICY` | classify, route | `current_state.json` | Policy for `select_route()` |
| `LUCY_AUGMENTED_PROVIDER` | provider_resolver | `current_state.json` | Provider preference |
| `LUCY_EVIDENCE_ENABLED` | execution_engine | `current_state.json` | Evidence fetching toggle |
| `LUCY_CONVERSATION_MODE_FORCE` | execution_engine | `current_state.json` | Conversation mode |
| `LUCY_SHARED_STATE_NAMESPACE` | everywhere | `runtime_bridge.py` | Multi-tenant state isolation |

## Key Design Rules

1. **Single entry point**: All surfaces call `main.run()`.
2. **Frozen dataclasses**: `ClassificationResult`, `RoutingDecision`, `ExecutionResult`, `RouterOutcome` are immutable. Use `dataclasses.replace()`.
3. **Provider resolution centralized**: Only `provider_resolver.py` reads `LUCY_AUGMENTED_PROVIDER`.
4. **Medical safety hardcoded**: `medical_context` → wikipedia, cannot be overridden.
5. **Route preservation on failure**: WEATHER stays WEATHER even if wttr.in fails.
6. **Memory persistence centralized**: Only `main._persist_memory_turn()` writes memory.
7. **Pure formatting**: `response_formatter.py` has no side effects, no I/O.

## Deprecated (still present for backward compatibility)

- `execute_plan_shell()` → delegates to `execute_plan_python()` + warning
- `execute_plan_parity()` → delegates to `execute_plan_python()` + warning
- `execute_plan_shadow` → alias to `execute_plan_parity`

## Test Coverage

- **Unit tests**: `pytest tools/router_py/` → 193 passed, 19 skipped
- **Contract tests**: `test_request_pipeline_contract.py` → all pass
- **End-to-end smoke**: `run("What is 2+2?")` → correct answer
