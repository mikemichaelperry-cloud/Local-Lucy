#!/usr/bin/env bash
# ROLE: Desktop launcher entrypoint for Local Lucy v8 Alpha
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Check for virtual environment
if [[ -d ".venv" ]]; then
    source .venv/bin/activate
fi

# Set Qt platform for compatibility
export QT_QPA_PLATFORM=xcb
export QT_QPA_PLATFORM_PLUGIN_PATH="${SCRIPT_DIR}/.venv/lib/python3.10/site-packages/PySide6/plugins" 2>/dev/null || true

# Core environment variables
export LUCY_ROOT="$SCRIPT_DIR"
export LUCY_UI_ROOT="${SCRIPT_DIR}/ui-v8"
export LUCY_RUNTIME_AUTHORITY_ROOT="${SCRIPT_DIR}/snapshots/opt-experimental-v8-dev"

# Set PYTHONPATH for module imports
export PYTHONPATH="${SCRIPT_DIR}/ui-v8:${SCRIPT_DIR}/snapshots/opt-experimental-v8-dev/tools:${SCRIPT_DIR}/snapshots/opt-experimental-v8-dev/tools/router_py:${PYTHONPATH:-}"
export LUCY_RUNTIME_NAMESPACE_ROOT="${SCRIPT_DIR}/state"
export LUCY_RUNTIME_CONTRACT_REQUIRED=1
export LUCY_ENABLE_INTERNET="${LUCY_ENABLE_INTERNET:-1}"
export LUCY_SESSION_MEMORY="${LUCY_SESSION_MEMORY:-1}"
export LUCY_VOICE_ENABLED="${LUCY_VOICE_ENABLED:-1}"
export LUCY_ROUTER_PY="${LUCY_ROUTER_PY:-1}"
export LUCY_LOCAL_MODEL="${LUCY_LOCAL_MODEL:-local-lucy}"
export LUCY_OLLAMA_API_URL="${LUCY_OLLAMA_API_URL:-http://127.0.0.1:11434/api/generate}"

# Check if UI exists
if [[ ! -d "ui-v8" ]]; then
    echo "ERROR: ui-v8 directory not found at ${LUCY_UI_ROOT}"
    echo "Please ensure Local Lucy v8 is properly installed."
    read -p "Press Enter to exit..."
    exit 1
fi

# Check for Ollama
if ! curl -s http://127.0.0.1:11434/api/tags > /dev/null 2>&1; then
    echo "WARNING: Ollama not running. Local Lucy requires Ollama."
    echo "Start Ollama with: ollama serve"
fi

echo "=========================================="
echo "  Local Lucy v8 Alpha"
echo "=========================================="
echo "ROOT: $LUCY_ROOT"
echo "UI:   $LUCY_UI_ROOT"
echo "Python Router: ENABLED"
echo "=========================================="
echo ""

# Launch the HMI
cd ui-v8
exec python3 -m app.main "$@"
