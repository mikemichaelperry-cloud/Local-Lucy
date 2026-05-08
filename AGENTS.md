# Local Lucy v8 — Codex Execution Rules

## Authority

- The authoritative working root is:
  /home/mike/lucy-v8/snapshots/opt-experimental-v8-dev

- Do not modify:
  - launcher structure
  - HMI structure
  - unrelated subsystems

- Backend is authoritative. UI must not fabricate state.

## System Privileges

- **Never use `sudo`.** The system blocks external sudo requests and the shell crashes.
- Make changes only within `~/lucy-v8/` directories.
- For system-level changes (e.g., systemd, global env vars), use user-level alternatives:
  - Modify `START_LUCY.sh` to export env vars
  - Use per-user systemd overrides (`~/.config/systemd/user/`) if available
  - Never edit `/etc/systemd/system/` or other root-owned paths

## Operating Principles

- No optimistic behavior
- No silent side effects
