#!/usr/bin/env bash
# Local Lucy v8 Alpha - Desktop Launcher
# One path: ui-v8/app/ contains all backend code

set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Qt platform configuration
export QT_QPA_PLATFORM=xcb
export QT_QPA_PLATFORM_PLUGIN_PATH="/usr/lib/x86_64-linux-gnu/qt6/plugins"

# Lucy paths
export LUCY_ROOT="$SCRIPT_DIR"
export LUCY_UI_ROOT="${SCRIPT_DIR}/ui-v8"
export LUCY_RUNTIME_NAMESPACE_ROOT="${SCRIPT_DIR}/state"

# Python path - app/ directory enables 'from backend import ...'
export PYTHONPATH="${SCRIPT_DIR}/ui-v8/app:${PYTHONPATH:-}"

# Runtime configuration
export LUCY_ROUTER_PY=1
export LUCY_LOCAL_MODEL=local-lucy
export LUCY_OLLAMA_API_URL=http://127.0.0.1:11434/api/generate
export LUCY_ENABLE_INTERNET=1
export LUCY_SESSION_MEMORY=1

# Launch HMI
cd ui-v8
exec python3 -m app.main "$@"
