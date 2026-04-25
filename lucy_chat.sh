#!/usr/bin/env bash
#
# Local Lucy V8 - Primary Chat Entry Point
# ROLE: AUTHORITATIVE CHAT INTERFACE for opt-experimental-v8-dev
#
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${SCRIPT_DIR}"

export LUCY_ROOT="${ROOT}"
export LUCY_RUNTIME_AUTHORITY_ROOT="${ROOT}"
export LUCY_CONF_DIR="${ROOT}/config"
export LUCY_TOOLS_DIR="${ROOT}/tools"

# Python router for execution
ROUTER_PY="${ROOT}/tools/router_py/main.py"
LOCAL_WORKER="${ROOT}/tools/local_worker.py"

# Environment defaults - NOW DEFAULT TO PYTHON
export LUCY_LOCAL_MODEL="${LUCY_LOCAL_MODEL:-local-lucy}"
export LUCY_OLLAMA_API_URL="${LUCY_OLLAMA_API_URL:-http://127.0.0.1:11434/api/generate}"
export LUCY_ENABLE_INTERNET="${LUCY_ENABLE_INTERNET:-1}"
export LUCY_AUGMENTATION_POLICY="${LUCY_AUGMENTATION_POLICY:-disabled}"
export LUCY_ROUTER_PY="${LUCY_ROUTER_PY:-1}"
export LUCY_EXEC_PY="${LUCY_EXEC_PY:-1}"

# Ensure state directories exist
mkdir -p "${ROOT}/state/namespaces/default"
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
