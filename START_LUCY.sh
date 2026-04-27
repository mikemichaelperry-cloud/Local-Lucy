#!/usr/bin/env bash
# Local Lucy v8 Alpha - Desktop Launcher
# One path: ui-v8/app/ contains all backend code

set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_HOME="$(dirname -- "$SCRIPT_DIR")"
cd "$SCRIPT_DIR"

# Source latency optimizations (token limits for long responses)
if [ -f "${SCRIPT_DIR}/config/latency_optimizations.env" ]; then
    source "${SCRIPT_DIR}/config/latency_optimizations.env"
fi

# Qt platform configuration
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-xcb}"
export QT_QPA_PLATFORM_PLUGIN_PATH="/usr/lib/x86_64-linux-gnu/qt6/plugins"

# Lucy paths
export LUCY_ROOT="$SCRIPT_DIR"
export LUCY_UI_ROOT="${SCRIPT_DIR}/ui-v8"
export LUCY_RUNTIME_NAMESPACE_ROOT="$SCRIPT_DIR"
export LUCY_RUNTIME_AUTHORITY_ROOT="$SCRIPT_DIR"
export LUCY_RUNTIME_REQUEST_HISTORY_FILE="$SCRIPT_DIR/state/request_history.jsonl"

# Voice runtime requirements
export LUCY_VOICE_RUNTIME_FILE="$SCRIPT_DIR/state/voice_runtime.json"
export LUCY_VOICE_CAPTURE_DIR="$SCRIPT_DIR/voice/ui_ptt"

# Python path - app/ directory enables 'from backend import ...'.
# Include /home/mike/.local because managed shells can set HOME to a sandbox
# home, hiding PySide6 from the normal user-site lookup.
export PYTHONPATH="${SCRIPT_DIR}/ui-v8/app:${WORKSPACE_HOME}/.local/lib/python3.10/site-packages:${PYTHONPATH:-}"

# Runtime configuration
export LUCY_ROUTER_PY=1
export LUCY_LOCAL_MODEL=local-lucy
export LUCY_OLLAMA_API_URL=http://127.0.0.1:11434/api/generate
export LUCY_ENABLE_INTERNET=1
export LUCY_SESSION_MEMORY=1

# Voice STT (Whisper) library path
export LD_LIBRARY_PATH="${SCRIPT_DIR}/runtime/voice/whisper.cpp/build/src:${SCRIPT_DIR}/runtime/voice/whisper.cpp/build/ggml/src:${LD_LIBRARY_PATH:-}"

V8_PYTHON="${SCRIPT_DIR}/ui-v8/.venv/bin/python3"
if [ -x "$V8_PYTHON" ]; then
    export LUCY_VOICE_PYTHON_BIN="$V8_PYTHON"
    APP_PYTHON="$V8_PYTHON"
else
    APP_PYTHON="/usr/bin/python3"
fi

# Launch HMI
cd ui-v8
exec "$APP_PYTHON" -m app.main "$@"
