#!/usr/bin/env bash
#
# Local Lucy V11 - Primary Chat Entry Point
# ROLE: AUTHORITATIVE CHAT INTERFACE for lucy-v11
#
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# Runtime authority root may be overridden (e.g. by tests using a fake root).
# The script's own directory remains the source for the Python entry points.
ROOT="${LUCY_ROOT:-${SCRIPT_DIR}}"

# Source user .env for API keys from the runtime root (if present)
if [ -f "${ROOT}/.env" ]; then
    source "${ROOT}/.env"
fi

export LUCY_ROOT="${ROOT}"
export LUCY_RUNTIME_AUTHORITY_ROOT="${ROOT}"
export LUCY_UI_ROOT="${ROOT}/ui-v10"
export LUCY_CONF_DIR="${ROOT}/config"
export LUCY_TOOLS_DIR="${ROOT}/tools"

if [ -n "${LUCY_RUNTIME_NAMESPACE_ROOT:-}" ]; then
    : # user override
else
    export LUCY_RUNTIME_NAMESPACE_ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/local-lucy-v11"
fi

# Python router for execution — always use the installation that contains this script
ROUTER_PY="${SCRIPT_DIR}/tools/router_py/main.py"
LOCAL_WORKER="${SCRIPT_DIR}/tools/local_worker.py"

# Environment defaults - NOW DEFAULT TO PYTHON
export LUCY_LOCAL_MODEL="${LUCY_LOCAL_MODEL:-local-lucy}"
export LUCY_OLLAMA_API_URL="${LUCY_OLLAMA_API_URL:-http://127.0.0.1:11434/api/generate}"
# Control toggles (evidence/augmentation) are loaded from current_state.json by
# the Python router.  Do not hard-code defaults here; that prevents the state
# file from being the single source of truth and breaks test overrides.

# Ensure state directories exist
mkdir -p "$LUCY_RUNTIME_NAMESPACE_ROOT/state/namespaces/default"
mkdir -p "$LUCY_RUNTIME_NAMESPACE_ROOT/logs"
mkdir -p "${ROOT}/logs"

# Check Ollama is available
if ! curl -s "${LUCY_OLLAMA_API_URL/\/api\/generate/}/api/tags" > /dev/null 2>&1; then
    echo "ERROR: Ollama is not running at ${LUCY_OLLAMA_API_URL}" >&2
    echo "Start Ollama with: ollama serve" >&2
    exit 1
fi

# Run chat via Python router
if [[ -x "${ROUTER_PY}" ]]; then
    exec python3 "${ROUTER_PY}" "$@"
elif [[ -x "${LOCAL_WORKER}" ]]; then
    exec python3 "${LOCAL_WORKER}" --chat "$@"
else
    echo "ERROR: No chat backend found." >&2
    echo "Expected one of: ${ROUTER_PY}, ${LOCAL_WORKER}" >&2
    exit 1
fi
