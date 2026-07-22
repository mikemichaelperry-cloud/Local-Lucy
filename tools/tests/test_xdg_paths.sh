#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"

ok(){ echo "OK: $*"; }
die(){ echo "FAIL: $*" >&2; exit 1; }

TMPD="$(mktemp -d)"
trap 'rm -rf "${TMPD}"' EXIT

PY_RUN="env -i PATH='${PATH}' HOME='${TMPD}/home' python3"

# ---------------------------------------------------------------------------
# Helper: run a Python snippet that imports tools.xdg_paths from the repo root.
# ---------------------------------------------------------------------------
run_python() {
  env -i PATH="${PATH}" "$@" python3 - <<PY
import os, sys
sys.path.insert(0, "${ROOT}")
from tools.xdg_paths import (
    lucy_data_dir,
    lucy_config_dir,
    lucy_cache_dir,
    lucy_state_dir,
    lucy_runtime_namespace_root,
    lucy_memory_db_path,
    lucy_state_db_path,
)
print("DATA:", lucy_data_dir())
print("CONFIG:", lucy_config_dir())
print("CACHE:", lucy_cache_dir())
print("STATE:", lucy_state_dir())
print("ROOT:", lucy_runtime_namespace_root())
print("MEMORY_DB:", lucy_memory_db_path())
print("STATE_DB:", lucy_state_db_path())
PY
}

# ---------------------------------------------------------------------------
# 1. Launcher block sets canonical namespace in START_LUCY.sh
# ---------------------------------------------------------------------------
launcher_block="$(sed -n '/^# Lucy paths$/,/^export LUCY_CACHE_DIR/p' "${ROOT}/START_LUCY.sh")"
launcher_vars="$(
  env -i PATH="${PATH}" HOME="${TMPD}/home" bash -c \
    'eval "$1"; echo "RUNTIME=$LUCY_RUNTIME_NAMESPACE_ROOT"; echo "CONFIG=$LUCY_CONFIG_DIR"; echo "CACHE=$LUCY_CACHE_DIR"' \
    _ "${launcher_block}"
)"
[[ "${launcher_vars}" == *"RUNTIME=${TMPD}/home/.local/share/local-lucy-v11"* ]] \
  || die "launcher did not set canonical runtime namespace:\n${launcher_vars}"
[[ "${launcher_vars}" == *"CONFIG=${TMPD}/home/.config/local-lucy-v11"* ]] \
  || die "launcher did not set canonical config dir:\n${launcher_vars}"
[[ "${launcher_vars}" == *"CACHE=${TMPD}/home/.cache/local-lucy-v11"* ]] \
  || die "launcher did not set canonical cache dir:\n${launcher_vars}"
ok "launcher block sets canonical local-lucy-v11 XDG paths"

# ---------------------------------------------------------------------------
# 2. Direct Python CLI with unset namespace resolves to XDG canonical path
# ---------------------------------------------------------------------------
output="$(run_python HOME="${TMPD}/home")"
[[ "${output}" == *"ROOT: ${TMPD}/home/.local/share/local-lucy-v11"* ]] \
  || die "direct Python CLI did not resolve canonical root:\n${output}"
[[ "${output}" == *"MEMORY_DB: ${TMPD}/home/.local/share/local-lucy-v11/state/memory.db"* ]] \
  || die "direct Python CLI did not resolve canonical memory.db:\n${output}"
ok "direct Python CLI resolves canonical XDG path"

# ---------------------------------------------------------------------------
# 3. Custom XDG_DATA_HOME / XDG_CONFIG_HOME / XDG_CACHE_HOME are respected
# ---------------------------------------------------------------------------
xdg_data="${TMPD}/xdg_data"
xdg_config="${TMPD}/xdg_config"
xdg_cache="${TMPD}/xdg_cache"
output="$(run_python HOME="${TMPD}/home" XDG_DATA_HOME="${xdg_data}" XDG_CONFIG_HOME="${xdg_config}" XDG_CACHE_HOME="${xdg_cache}")"
[[ "${output}" == *"DATA: ${xdg_data}/local-lucy-v11"* ]] || die "custom XDG_DATA_HOME not respected:\n${output}"
[[ "${output}" == *"CONFIG: ${xdg_config}/local-lucy-v11"* ]] || die "custom XDG_CONFIG_HOME not respected:\n${output}"
[[ "${output}" == *"CACHE: ${xdg_cache}/local-lucy-v11"* ]] || die "custom XDG_CACHE_HOME not respected:\n${output}"
[[ "${output}" == *"STATE: ${xdg_data}/local-lucy-v11/state"* ]] || die "custom XDG_DATA_HOME state dir wrong:\n${output}"
ok "custom XDG_*_HOME values are respected"

# ---------------------------------------------------------------------------
# 4. Arbitrary cwd still resolves canonical path
# ---------------------------------------------------------------------------
output="$(cd /tmp && run_python HOME="${TMPD}/home")"
[[ "${output}" == *"ROOT: ${TMPD}/home/.local/share/local-lucy-v11"* ]] \
  || die "arbitrary cwd changed canonical resolution:\n${output}"
ok "arbitrary cwd still resolves canonical path"

# ---------------------------------------------------------------------------
# 5. Temporary HOME produces path under temp HOME
# ---------------------------------------------------------------------------
temp_home="${TMPD}/another_home"
output="$(run_python HOME="${temp_home}")"
[[ "${output}" == *"ROOT: ${temp_home}/.local/share/local-lucy-v11"* ]] \
  || die "temporary HOME not respected:\n${output}"
ok "temporary HOME produces path under temp HOME"

# ---------------------------------------------------------------------------
# 6. LUCY_RUNTIME_NAMESPACE_ROOT override still wins
# ---------------------------------------------------------------------------
override="${TMPD}/override_root"
output="$(run_python HOME="${TMPD}/home" LUCY_RUNTIME_NAMESPACE_ROOT="${override}")"
[[ "${output}" == *"ROOT: ${override}"* ]] || die "LUCY_RUNTIME_NAMESPACE_ROOT override did not win:\n${output}"
[[ "${output}" == *"STATE: ${override}/state"* ]] || die "override state dir wrong:\n${output}"
ok "LUCY_RUNTIME_NAMESPACE_ROOT override still wins"

echo "PASS: test_xdg_paths"
