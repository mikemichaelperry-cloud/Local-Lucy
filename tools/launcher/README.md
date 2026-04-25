# Local Lucy Supported Entry Surfaces

This file declares the operator-facing entry surfaces for the active `opt-experimental-v7-dev` snapshot.

## Supported Current Surfaces

### HMI
- Path: `/home/mike/lucy/ui-v7/app/main.py`
- Preferred launcher: `/home/mike/lucy/snapshots/opt-experimental-v7-dev/tools/start_local_lucy_hmi_opt_experimental_v7_dev.sh`
- Desktop surface: `/home/mike/Desktop/Local Lucy HMI v7.desktop`

### Terminal Authority
- Path: `/home/mike/lucy/snapshots/opt-experimental-v7-dev/tools/start_local_lucy_opt_experimental_v7_dev.sh`
- Use this as the terminal authority path for current v7 workflows.

### Codex Preprocess Wrapper
- Path: `/home/mike/lucy/snapshots/opt-experimental-v7-dev/tools/start_local_lucy_opt_experimental_v7_dev_codex_preprocess.sh`
- Specialized wrapper for local preprocessing before Codex work.
- Not the default operator path.

### Voice / PTT
- Path: `/home/mike/lucy/snapshots/opt-experimental-v7-dev/tools/lucy_voice_ptt.sh`

### Handoff Write / Resume
- Write: `/home/mike/lucy/snapshots/opt-experimental-v7-dev/tools/write_local_lucy_handoff.sh`
- Resume: `/home/mike/lucy/snapshots/opt-experimental-v7-dev/tools/resume_local_lucy_from_handoff.sh`

## Backend / Authority Review

- Active authority chain:
  - Terminal launcher: `/home/mike/lucy/snapshots/opt-experimental-v7-dev/tools/start_local_lucy_opt_experimental_v7_dev.sh`
  - HMI bridge: `/home/mike/lucy/ui-v7/app/services/runtime_bridge.py`
  - Submit endpoint: `/home/mike/lucy/snapshots/opt-experimental-v7-dev/tools/runtime_request.py`
  - Backend executable: `/home/mike/lucy/snapshots/opt-experimental-v7-dev/lucy_chat.sh`
  - Governed manifest source: `/home/mike/lucy/snapshots/opt-experimental-v7-dev/tools/router/core/route_manifest.py`
  - Manifest is consumed through `/home/mike/lucy/snapshots/opt-experimental-v7-dev/tools/router/plan_to_pipeline.py` and enforced by `/home/mike/lucy/snapshots/opt-experimental-v7-dev/tools/router/execute_plan.sh`
- Default runtime authority is snapshot-local.
- Default runtime namespace is version-local: `~/.codex-api-home/lucy/runtime-v7`
- Explicit non-default authority override for launcher/request/voice test seams: `LUCY_RUNTIME_AUTHORITY_ROOT=/abs/path`
- Operator inspection command:
```bash
python3 /home/mike/lucy/snapshots/opt-experimental-v7-dev/tools/diag/print_runtime_authority_chain.py
```
