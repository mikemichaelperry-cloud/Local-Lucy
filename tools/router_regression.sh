#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ -x "${SCRIPT_DIR}/router/router_regression.sh" ]]; then
  exec "${SCRIPT_DIR}/router/router_regression.sh" "$@"
fi
exec "${SCRIPT_DIR}/router/router_regression_v1.sh" "$@"
