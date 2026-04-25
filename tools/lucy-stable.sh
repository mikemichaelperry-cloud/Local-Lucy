#!/usr/bin/env bash
# ROLE: LEGACY / DEPRECATED SURFACE
# Retained for compatibility/history; do not use for new workflows.
# Preferred replacement: tools/start_local_lucy_opt_experimental_v6_dev.sh
set -euo pipefail
echo "=== Local Lucy (STABLE) ==="
echo "Model: local-lucy-stable"
echo "Started: $(date -Is)"
echo
exec ollama run local-lucy-stable
