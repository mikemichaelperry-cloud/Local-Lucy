#!/usr/bin/env bash
# ROLE: PRIMARY AUTHORITATIVE ENTRYPOINT for Local Lucy v8
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)"
AUTHORITY_ROOT_OVERRIDE="${LUCY_RUNTIME_AUTHORITY_ROOT:-}"
if [[ -n "${AUTHORITY_ROOT_OVERRIDE}" ]]; then
  ROOT="$(CDPATH= cd -- "${AUTHORITY_ROOT_OVERRIDE}" 2>/dev/null && pwd)" || {
    echo "ERR: invalid LUCY_RUNTIME_AUTHORITY_ROOT: ${AUTHORITY_ROOT_OVERRIDE}" >&2
    exit 2
  }
else
  ROOT="${DEFAULT_ROOT}"
fi
if [[ "$(basename -- "${ROOT}")" != "opt-experimental-v8-dev" ]]; then
  echo "ERR: active v8 terminal authority requires opt-experimental-v8-dev root, got: ${ROOT}" >&2
  exit 2
fi
cd "$ROOT"

if [[ -n "${LUCY_UI_ROOT:-}" ]]; then
  UI_ROOT="${LUCY_UI_ROOT}"
else
  WORKSPACE_ROOT="$(dirname -- "$(dirname -- "${ROOT}")")"
  UI_ROOT="${WORKSPACE_ROOT}/ui-v8"
fi
UI_ROOT="$(CDPATH= cd -- "${UI_ROOT}" 2>/dev/null && pwd)" || {
  echo "ERR: invalid LUCY_UI_ROOT/UI_ROOT: ${UI_ROOT}" >&2
  exit 2
}
if [[ "$(basename -- "${UI_ROOT}")" != "ui-v8" ]]; then
  echo "ERR: active v8 terminal authority requires ui-v8 root, got: ${UI_ROOT}" >&2
  exit 2
fi

export LUCY_ROOT="$ROOT"
export LUCY_RUNTIME_AUTHORITY_ROOT="$ROOT"
export LUCY_UI_ROOT="${UI_ROOT}"
export LUCY_TOOLS_DIR="$ROOT/tools"
export LUCY_CONF_DIR="$ROOT/config"
export LUCY_ENABLE_INTERNET="${LUCY_ENABLE_INTERNET:-1}"
export LUCY_SESSION_MEMORY="${LUCY_SESSION_MEMORY:-1}"
export LUCY_VOICE_ENABLED="${LUCY_VOICE_ENABLED:-1}"
export LUCY_AUGMENTATION_POLICY="${LUCY_AUGMENTATION_POLICY:-disabled}"
export LUCY_AUGMENTED_PROVIDER="${LUCY_AUGMENTED_PROVIDER:-wikipedia}"
export LUCY_LOCAL_MODEL="${LUCY_LOCAL_MODEL:-local-lucy}"
export LUCY_OLLAMA_API_URL="${LUCY_OLLAMA_API_URL:-http://127.0.0.1:11434/api/generate}"
export LUCY_LOCAL_KEEP_ALIVE="${LUCY_LOCAL_KEEP_ALIVE:-10m}"
export LUCY_LOCAL_WORKER_TRANSPORT="${LUCY_LOCAL_WORKER_TRANSPORT:-unix}"
export LUCY_RUNTIME_NAMESPACE_ROOT="${LUCY_RUNTIME_NAMESPACE_ROOT:-${ROOT}/state}"
export LUCY_RUNTIME_CONTRACT_REQUIRED=1
export LUCY_LAUNCHER_LABEL="opt-experimental-v8-dev"
export LUCY_LAUNCHER_FAMILY="launcher v8"

echo "Local Lucy v8 started"
echo "ROOT: $ROOT"
echo "UI_ROOT: $UI_ROOT"

# Keep running to satisfy lifecycle
tail -f /dev/null
