# ADR 0004: XDG Base Directory Compliance

## Status
Accepted — implemented 2026-06-14

## Context
Local Lucy v10 originally stored runtime state under `~/.codex-api-home/lucy/runtime-v10/`. This path is non-standard, hardcoded in many places, and mixes code authority with runtime data.

## Decision
- Use `~/.local/share/local-lucy/` (XDG data home) as the canonical runtime namespace root.
- Keep `~/.codex-api-home/...` as a legacy fallback for existing installations.
- Introduce `tools/xdg_paths.py` for centralized path resolution.
- Set `LUCY_RUNTIME_NAMESPACE_ROOT` in `START_LUCY.sh`.

## Consequences
- Cleaner separation between project code (`LUCY_ROOT`) and runtime data.
- Easier backups and uninstalls.
- Migration path needed for users upgrading from legacy paths.
