# Local Lucy V11 — Supported Entry Surfaces

This file declares the operator-facing entry surfaces for the active V11 runtime.

## Supported Current Surfaces

### Desktop HMI (primary)
- Source: `ui-v10/`
- Main entry: `ui-v10/app/main.py`
- Desktop shortcut: `START_LUCY.sh`
- Runtime bridge: `ui-v10/app/services/runtime_bridge.py`

### Terminal / CLI
- Main entry: `lucy_chat.sh`
- Runtime control: `tools/runtime_control.py`
- Runtime request: `tools/runtime_request.py`

### Web Adapter (optional)
- Source: `web_adapter/`
- Enable with: `LUCY_WEB_ENABLED=1 python -m web_adapter`
- Default bind: `127.0.0.1:8765`

### Voice / PTT
- Source: `tools/voice/`
- Workers: `tools/voice/whisper_worker.py`, `tools/voice/kokoro_session_worker.py`

## Backend / Authority

- Active authority chain:
  - Launcher: `START_LUCY.sh` / `lucy_chat.sh`
  - Core pipeline: `tools/router_py/main.py::run(...)`
  - Router: `tools/router_py/classify.py`, `tools/router_py/policy_router.py`
  - Execution engine: `tools/router_py/execution_engine.py`
  - State/runtime control: `tools/runtime_control.py`
- Default runtime namespace: `~/.codex-api-home/lucy/runtime-v10`
- Authority override: `LUCY_RUNTIME_AUTHORITY_ROOT=/abs/path`
