#!/bin/bash
# DEPRECATED: Python-native path is now authoritative.
# This shim delegates to router_py.main for backward compatibility.
# Original script preserved as execute_plan.sh.legacy

export LUCY_EXEC_PY=1
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
LUCY_ROOT="$(cd -- "${SCRIPT_DIR}/../../../../" && pwd)"
export PYTHONPATH="${LUCY_ROOT}/tools:${PYTHONPATH:-}"
cd "${LUCY_ROOT}"
python3 -m router_py.main "$@"
