#!/usr/bin/env bash
# ROLE: LEGACY / DEPRECATED SURFACE
# Retained for compatibility/history; do not use for new workflows.
# Preferred replacement: tools/start_local_lucy_opt_experimental_v6_dev.sh
set -euo pipefail

MODEL="${1:-local-lucy}"
TS="$(date -Is)"

echo "=== Local Lucy v0 ==="
echo "Model: $MODEL"
echo "Keel:  ~/lucy/keel/keel.yaml"
echo "Session start: $TS"
echo

echo "$TS | START | model=$MODEL" >> ~/lucy/audit/audit.log

ollama run "$MODEL"

TS_END="$(date -Is)"
echo "$TS_END | END   | model=$MODEL" >> ~/lucy/audit/audit.log
