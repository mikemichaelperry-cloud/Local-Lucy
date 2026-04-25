# Local Lucy v8 — Codex Execution Rules

## Authority

- The authoritative working root is:
  /home/mike/lucy-v8/snapshots/opt-experimental-v8-dev

- Do not modify:
  - launcher structure
  - HMI structure
  - unrelated subsystems

- Backend is authoritative. UI must not fabricate state.

## Operating Principles

- No optimistic behavior
- No silent side effects
