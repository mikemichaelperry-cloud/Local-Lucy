# LOCAL_LUCY_CONSOLIDATED_STATUS
Timestamp: 2026-03-20T21:33:04+0200

## Current Position
Local Lucy is now operating as a real authoritative desktop HMI, not just a UI shell or smoke-test scaffold.

From `/home/mike/lucy/ui`, the console can:
- display authoritative runtime state from `/home/mike/lucy/runtime/state`
- show live logs and persisted request/result history
- submit requests through `/home/mike/lucy/snapshots/opt-experimental-v6-dev/tools/runtime_request.py`
- change `mode`, `memory`, `evidence`, and `voice` through `/home/mike/lucy/snapshots/opt-experimental-v6-dev/tools/runtime_control.py`
- run/stop the runtime through `/home/mike/lucy/snapshots/opt-experimental-v6-dev/tools/runtime_lifecycle.py`
- reload the active profile through `/home/mike/lucy/snapshots/opt-experimental-v6-dev/tools/runtime_profile.py`
- expose different operating depths through `Operator`, `Advanced`, `Engineering`, and `Service`

## HMI Status
The HMI is now a structured Qt Widgets operator console with:
- top status chips
- left control column
- center conversation/history pane
- right diagnostics/runtime pane
- bottom event log
- top-bar interface level selector

### Interface Levels
- `Operator`
  - submit
  - run / stop
  - mode / memory / evidence / voice
  - compact recent history
  - concise runtime and request summary
- `Advanced`
  - everything in Operator
  - profile reload
  - richer diagnostics
  - history selection and drill-down
- `Engineering`
  - everything in Advanced
  - expanded state/runtime metadata
  - raw selected request metadata
  - file/path visibility
- `Service`
  - everything in Engineering
  - read-only maintenance / retention visibility
  - no destructive service actions live yet

## Authoritative Runtime Truth
- `profile=opt-experimental-v6-dev`
- `model=local-lucy`
- `mode=auto`
- `memory=on`
- `evidence=on`
- `voice=on`
- `status=ready`
- `last_updated=2026-03-20T19:09:38Z`
- `lifecycle.running=false`
- `lifecycle.status=stopped`
- `lifecycle.pid=none`

## Authoritative Endpoint Surface
- Runtime control:
  - `python3 /home/mike/lucy/snapshots/opt-experimental-v6-dev/tools/runtime_control.py set-mode --value {auto|online|offline}`
  - `python3 /home/mike/lucy/snapshots/opt-experimental-v6-dev/tools/runtime_control.py set-memory --value {on|off}`
  - `python3 /home/mike/lucy/snapshots/opt-experimental-v6-dev/tools/runtime_control.py set-evidence --value {on|off}`
  - `python3 /home/mike/lucy/snapshots/opt-experimental-v6-dev/tools/runtime_control.py set-voice --value {on|off}`
  - `python3 /home/mike/lucy/snapshots/opt-experimental-v6-dev/tools/runtime_control.py show-state`
- Runtime request:
  - `python3 /home/mike/lucy/snapshots/opt-experimental-v6-dev/tools/runtime_request.py submit --text "..."`
- Runtime lifecycle:
  - `python3 /home/mike/lucy/snapshots/opt-experimental-v6-dev/tools/runtime_lifecycle.py start`
  - `python3 /home/mike/lucy/snapshots/opt-experimental-v6-dev/tools/runtime_lifecycle.py stop`
  - `python3 /home/mike/lucy/snapshots/opt-experimental-v6-dev/tools/runtime_lifecycle.py status`
- Runtime profile:
  - `python3 /home/mike/lucy/snapshots/opt-experimental-v6-dev/tools/runtime_profile.py reload`
  - `python3 /home/mike/lucy/snapshots/opt-experimental-v6-dev/tools/runtime_profile.py show`

## Boundaries Still Intentionally In Place
- no profile switching, only profile reload
- no archive/history browser UI yet
- no destructive service actions
- no broader session/launcher control beyond the explicit authoritative endpoints

## Continuity
- Latest handoff:
  - `/home/mike/lucy/snapshots/opt-experimental-v6-dev/dev_notes/SESSION_HANDOFF_2026-03-20T21-23-20+0200.md`
- Handoff writer:
  - `/home/mike/lucy/snapshots/opt-experimental-v6-dev/tools/write_local_lucy_handoff.sh`
- Resume helper:
  - `/home/mike/lucy/snapshots/opt-experimental-v6-dev/tools/resume_local_lucy_from_handoff.sh`

## Summary
The backend authority model is in place, and the HMI is now a real layered operator console rather than a prototype. The next work should deepen selected surfaces deliberately, not flatten more controls into the default Operator view.
