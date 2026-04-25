# ChatGPT Review Report: Session Memory Toggle Architecture
Date: February 20, 2026
Prepared for: external architecture review
Snapshot: `/home/mike/lucy/snapshots/opt-experimental-v1`

## Scope
This report summarizes an implementation review of session-scoped conversational memory behavior in text and voice paths, with focus on architectural safety, determinism, and state bleed risk.

## Executive Assessment
Overall assessment: **mostly sound**, with one concrete hardening gap.

- Session continuity works in both text and voice paths.
- Memory injection is scoped to LOCAL answering and does not flow into EVIDENCE/NEWS paths.
- State is primarily session-local (temp files + process lifetime), but env-var overrides can intentionally rebind memory file locations.
- Golden/system regressions are not explicitly pinning session-memory env state, which is a reproducibility risk for future changes.

## What Is Implemented (Verified)
### 1) Toggle mechanism type
- **A) Environment variable**: implemented.
  - `LUCY_SESSION_MEMORY` in `lucy_chat.sh:20`
  - Exported in launcher `tools/start_local_lucy_opt_experimental_v1.sh:12`

- **B) In-memory shell variables**: implemented in NL wrapper.
  - Arrays `MEM_USER` and `MEM_ASSIST` in `tools/lucy_nl_chat.sh:25-26`

- **C) Temp file session state**: implemented.
  - NL memory file path in `tools/lucy_nl_chat.sh:27-37`
  - Router memory input via `LUCY_CHAT_MEMORY_FILE` in `tools/lucy_nl_chat.sh:207`
  - Voice memory file in `tools/lucy_voice_ptt.sh:43`
  - Voice->NL memory handoff in `tools/lucy_voice_ptt.sh:525`

- **D) Prompt-level behavior injection**: implemented.
  - Router assembles memory context in `lucy_chat.sh:223-247`
  - Injected only on local route in `lucy_chat.sh:350-356`
  - Consumed in local answer tool `tools/local_answer.sh:9,63-65`

## Architectural Soundness Against Required Conditions
### Condition 1: Strictly session-scoped
Status: **mostly true**.
- Memory files are process/session scoped (`$$` suffix) and cleaned on exit:
  - `tools/start_local_lucy_opt_experimental_v1.sh:19,23`
  - `tools/lucy_voice_ptt.sh:43,84`
- Risk remains if a caller intentionally sets `LUCY_NL_MEMORY_FILE` or `LUCY_CHAT_MEMORY_FILE` to a persistent path.

### Condition 2: No snapshot mutation
Status: **true for model behavior toggle path**.
- Memory flow uses temp runtime files under `tmp/run` and environment variables.
- No evidence found of writing into immutable source/config paths as part of toggle behavior.

### Condition 3: Does not affect golden determinism unless explicitly enabled
Status: **partially true; needs hardening**.
- Local golden cases call `tools/local_answer.sh` directly (`tools/golden_eval.sh:119`) without chat memory file feed.
- However, system legs launched by golden (`router/full regressions`) are not explicitly pinning memory-related env vars:
  - `tools/golden_eval.sh:220,242`
- This leaves future susceptibility to hidden state if wrappers/scripts later consume inherited memory env.

## Isolation and Security Review
### Evidence-mode isolation
Status: **clean**.
- Memory context injection path is inside `run_local` only (`lucy_chat.sh:345-356`).
- EVIDENCE/NEWS routes do not receive `LUCY_SESSION_MEMORY_CONTEXT`.

### Prompt-injection toggle risk
Status: **mostly controlled**.
- Toggle state changes occur through command handling in wrappers:
  - `/memory on|off|show|clear` in `tools/lucy_nl_chat.sh:130-161`
  - Voice memory commands in `tools/lucy_voice_ptt.sh:114-139,816-825`
- User prompt text alone cannot directly set shell env; risk depends on wrapper command interpretation surface, which appears explicit and bounded.

## Determinism Risk Statement
Current architecture is reproducible in common paths but has a **future-proofing gap**:
- Golden/system scripts should force known values for memory-related env vars (on/off + empty file vars) to prevent hidden dependency on parent-shell state.

## Recommended Hardening (Actionable)
1. In `tools/golden_eval.sh`, set deterministic env at script start:
   - `export LUCY_SESSION_MEMORY=0`
   - `unset LUCY_CHAT_MEMORY_FILE LUCY_NL_MEMORY_FILE LUCY_SESSION_MEMORY_CONTEXT`
2. Apply the same pinning in `tools/full_regression_v2.sh` and router regression entrypoints.
3. In `lucy_chat.sh`, optionally reject non-temp memory files unless an explicit override flag is set.
4. Add a regression case proving identical golden outputs with and without inherited memory env in the parent shell.

## Bottom Line
The implementation is a valid and useful session-continuity layer. It improves conversational ergonomics (especially voice) without evident contamination of evidence routing. The remaining issue is deterministic test harness pinning, which is straightforward to fix.
