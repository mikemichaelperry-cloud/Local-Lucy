# ChatGPT Session Update: Memory Determinism + Prompt v1.1-soft
Date: February 20, 2026
Project root: `/home/mike/lucy/snapshots/opt-experimental-v1`

## Summary
This session focused on three tracks:
1. Confirming architecture and risk posture of session memory behavior.
2. Hardening determinism in regression/golden scripts.
3. Implementing and activating the `v1.1-soft` consolidated system prompt.

## 1) Architecture Review Findings (Code-Verified)
- Session memory is implemented across env + session temp files + prompt injection on LOCAL path.
- Evidence/news paths are isolated from session memory context injection.
- Determinism gap identified: harness scripts did not explicitly pin memory-related env vars.

Key code paths reviewed:
- `lucy_chat.sh`
- `tools/lucy_nl_chat.sh`
- `tools/lucy_voice_ptt.sh`
- `tools/golden_eval.sh`
- `tools/full_regression_v2.sh`
- `tools/router/router_regression_v1.sh`

## 2) Determinism Hardening Applied
Added the following lines near the top of each regression/eval script:

```bash
export LUCY_SESSION_MEMORY=0
unset LUCY_CHAT_MEMORY_FILE
unset LUCY_NL_MEMORY_FILE
unset LUCY_SESSION_MEMORY_CONTEXT
```

Updated files:
- `/home/mike/lucy/snapshots/opt-experimental-v1/tools/golden_eval.sh`
- `/home/mike/lucy/snapshots/opt-experimental-v1/tools/full_regression_v2.sh`
- `/home/mike/lucy/snapshots/opt-experimental-v1/tools/router/router_regression_v1.sh`

Outcome:
- Regression and golden runs are now pinned against inherited session-memory state.

## 3) Prompt Upgrade Implemented (`v1.1-soft`)
Replaced prompt content with `LOCAL LUCY - CONSOLIDATED SYSTEM PROMPT v1.1-soft (RIGOR + GENTLE DELIVERY)`.

Updated files:
- `/home/mike/lucy/snapshots/opt-experimental-v1/config/system_prompt.dev.txt`
- `/home/mike/lucy/snapshots/opt-experimental-v1/config/Modelfile.local-lucy-mem`

Prompt includes:
- Fact/assumption separation
- Explicit dependency disclosure
- Deterministic architectural constraints
- Safety boundaries
- Warm-but-controlled delivery style

## 4) Model Rebuild + Smoke Validation
### Rebuild
Command:
- `./tools/dev_rebuild_mem_model.sh`

Result:
- Successful model rebuild (`local-lucy-mem`), manifest written, rebuild complete.

### Smoke checks
1. Command:
- `./tools/local_answer.sh "What is recursion in one sentence?"`
Result:
- Returned correct one-sentence recursion definition.

2. Command:
- `./lucy_chat.sh "local: Give me a simple schnitzel recipe structure only"`
Result:
- Returned validated local answer with structure-only ingredient list (no quantities).

## 5) Current State
- Determinism hardening for memory-related env bleed: DONE.
- Prompt `v1.1-soft` implementation: DONE.
- Runtime model rebuild after prompt change: DONE.
- Basic post-change functional smoke checks: PASS.

