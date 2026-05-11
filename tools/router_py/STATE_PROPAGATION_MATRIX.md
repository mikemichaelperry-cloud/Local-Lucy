# State Propagation Matrix

Stage 2 deliverable: documents what state flows between every pipeline stage.

## Pipeline Stages

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   Entry     │───→│  Classify   │───→│    Route    │───→│   Execute   │───→ RouterOutcome
│ (run())     │    │  (intent)   │    │  (policy)   │    │  (engine)   │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
      │                   │                  │                  │
   question          Classification    RoutingDecision    ExecutionResult
   context           Result
```

## Matrix: What flows where

| From → To | Carries | Type | Source of truth | Notes |
|-----------|---------|------|-----------------|-------|
| **Entry → Classify** | `question`, `surface` | `str` | caller | `run(question, surface="cli")` |
| | `LUCY_SESSION_MEMORY` | `env` | `current_state.json` | Enables `_memory_routing_gate()` |
| **Classify → Route** | `intent_family`, `confidence` | `ClassificationResult` | embedding router | Also `needs_web`, `force_local`, `evidence_reason` |
| | `LUCY_AUGMENTATION_POLICY` | `env` | `current_state.json` | `fallback_only`, `direct_allowed`, `disabled` |
| | `LUCY_AUGMENTED_PROVIDER` | `env` | `current_state.json` | `wikipedia`, `openai`, `kimi` |
| **Route → Execute** | `route`, `provider`, `mode` | `RoutingDecision` | `select_route()` | Frozen dataclass — immutable |
| | `evidence_mode`, `evidence_reason` | `RoutingDecision` | policy + classification | `medical_context` forces wikipedia |
| | `ephemeral` | `RoutingDecision` | keyword detection | weather/news/time = True |
| **Execute → Outcome** | `response_text`, `status` | `ExecutionResult` | `ExecutionEngine` | Converted to `RouterOutcome` in `main.py` |
| | `execution_time_ms` | `int` | `time.time()` delta | Added in `main.py` wrapper |
| **Outcome → Persistence** | `response_text` | `str` | `RouterOutcome` | SQLite `store_turn()` + text file |
| | `route`, `provider` | `str` | `RouterOutcome` | `last_outcome.env` telemetry |
| | `feedback` | `FeedbackEntry` | `feedback_parser.py` | `user_feedback.jsonl` |

## Environment Variable Contracts

| Variable | Read at | Written by | Purpose |
|----------|---------|------------|---------|
| `LUCY_SESSION_MEMORY` | classify, execute, outcome | `current_state.json` | Enable memory gate + persistence |
| `LUCY_AUGMENTATION_POLICY` | classify, route | `current_state.json` | Policy for `select_route()` |
| `LUCY_AUGMENTED_PROVIDER` | classify, route, execute | `current_state.json` | Provider preference (overridden by medical) |
| `LUCY_EVIDENCE_ENABLED` | execute | `current_state.json` | Evidence fetching toggle |
| `LUCY_CONVERSATION_MODE_FORCE` | execute | `current_state.json` | Conversation mode |
| `LUCY_FORCE_LOCAL` | execute (shell path) | `main.py` (from `force_local`) | Creative writing protection |
| `LUCY_SHARED_STATE_NAMESPACE` | everywhere | `runtime_bridge.py` | Multi-tenant state isolation |
| `LUCY_CHAT_MEMORY_FILE` | execute | default | Legacy text-file memory path |
| `LUCY_RUNTIME_CHAT_MEMORY_FILE` | execute | `runtime_bridge.py` | Runtime-specific memory path |

## Context Dict Contract (legacy → PipelineContext)

The ad-hoc dict built in `_delegate_execution_to_python()` is now formalized as `PipelineContext`:

| Field | Old key | New attr | Populated by | Consumed by |
|-------|---------|----------|--------------|-------------|
| question | `question` | `.question` | `main.run()` | `ExecutionEngine.execute()` |
| session_id | `session_id` | `.session_id` | `os.environ` | SQLite state manager |
| state_namespace | `state_namespace` | `.state_namespace` | `os.environ` | state file paths |
| augmentation_policy | `augmentation_policy` | `.augmentation_policy` | `os.environ` | policy checks |
| evidence_enabled | `evidence_enabled` | `.evidence_enabled` | `os.environ` | evidence fetch |
| conversation_mode | `conversation_mode_active` | `.conversation_mode_active` | `os.environ` | prompt building |
| augmented_provider | `augmented_provider` | `.augmented_provider` | `os.environ` | provider dispatch |
| surface | `surface` | `.surface` | caller | telemetry |
| memory_enabled | *(implicit)* | `.memory_enabled` | `os.environ` | memory load/store |
| force_local | *(implicit)* | `.force_local` | `ClassificationResult` | shell env pass |

## Known State Leaks

1. **Voice paths** (`streaming_voice.py`, `voice_tool.py`, `runtime_voice.py`) build their own `ExecutionEngine` context dicts — they don't use `PipelineContext.from_env()`.
2. **Provider resolution** happens in both `classify.py` (`_resolve_provider_preference()`) AND `execution_engine.py` (context check + `dataclasses.replace()`). Need to centralize in Stage 3.
3. **Memory persistence** happens in `main.py` (post-execution) AND `execution_engine.py` (some routes). Need to single-source in Stage 6.

## Migration Path

| Stage | Action |
|-------|--------|
| Stage 2 (now) | Create `request_types.py`, document matrix |
| Stage 3 | `request_pipeline.py` imports from `request_types`; builds `PipelineContext` |
| Stage 5 | Migrate `classify.py`, `execution_engine.py`, `main.py` to import from `request_types` |
| Stage 6 | Centralize memory persistence; use `PipelineContext` everywhere |
