#!/usr/bin/env bash
# ROLE: LEGACY / DEPRECATED SURFACE
# Retained for compatibility/history; do not use for new workflows.
# Preferred replacement: config/launcher/desktop_launchers.tsv generated surfaces.
set -euo pipefail

HOME_DIR="${HOME}"
LUCY_ROOT="${HOME_DIR}/lucy"
LOG_DIR="${LUCY_ROOT}/logs"
LOG_FILE="${LOG_DIR}/stable_desktop.log"

mkdir -p "${LOG_DIR}"

# These are replaced by the parent script with absolute paths.
LAUNCHER="/home/mike/lucy/snapshots/dev-evidence-orchestrator-v1/tools/lucy-stable.sh"
WORKDIR="/home/mike/lucy/snapshots/dev-evidence-orchestrator-v1"

{
  echo "=== Local Lucy stable desktop launch ==="
  echo "ts=$(date -Is)"
  echo "pwd_before=$(pwd)"
  echo "workdir=${WORKDIR}"
  echo "launcher=${LAUNCHER}"
  echo "user=$(id -un)"
  echo "shell=${SHELL:-}"
  echo "path=${PATH:-}"
  echo
} >> "${LOG_FILE}" 2>&1

cd "${WORKDIR}" >> "${LOG_FILE}" 2>&1 || true

# Run via bash so non-executable scripts still work predictably.
bash "${LAUNCHER}" >> "${LOG_FILE}" 2>&1
