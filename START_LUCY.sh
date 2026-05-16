#!/usr/bin/env bash
# Local Lucy v8 Alpha - Desktop Launcher
# One path: ui-v8/app/ contains all backend code

set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_HOME="$(dirname -- "$SCRIPT_DIR")"
cd "$SCRIPT_DIR"

# Source user .env for API keys (if present)
if [ -f "${SCRIPT_DIR}/.env" ]; then
    source "${SCRIPT_DIR}/.env"
fi

# Source latency optimizations (token limits for long responses)
if [ -f "${SCRIPT_DIR}/config/latency_optimizations.env" ]; then
    source "${SCRIPT_DIR}/config/latency_optimizations.env"
fi

# Qt platform configuration
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-xcb}"
export QT_QPA_PLATFORM_PLUGIN_PATH="/usr/lib/x86_64-linux-gnu/qt6/plugins"

# Lucy paths
export LUCY_ROOT="$SCRIPT_DIR"
export LUCY_UI_ROOT="${SCRIPT_DIR}/ui-v8"
# Unify all runtime state (JSON, SQLite, logs) to the user-local directory
# where StateWriter and backend defaults already write. This eliminates the
# split-brain where HMI reads from /home/mike/lucy-v8/state/ but router
# writes to ~/.codex-api-home/lucy/runtime-v8/state/.
export LUCY_RUNTIME_NAMESPACE_ROOT="$HOME/.codex-api-home/lucy/runtime-v8"
export LUCY_RUNTIME_AUTHORITY_ROOT="$SCRIPT_DIR"

# Voice capture directory stays in project tree (temporary audio, not persistent state)
export LUCY_VOICE_CAPTURE_DIR="$SCRIPT_DIR/voice/ui_ptt"

# Python path - app/ directory enables 'from backend import ...'.
# Include /home/mike/.local because managed shells can set HOME to a sandbox
# home, hiding PySide6 from the normal user-site lookup.
export PYTHONPATH="${SCRIPT_DIR}/ui-v8/app:${WORKSPACE_HOME}/.local/lib/python3.10/site-packages:${PYTHONPATH:-}"

# Router decision logging (enables feedback learning pipeline)
export LUCY_ROUTER_LOG_DIR="${LUCY_RUNTIME_NAMESPACE_ROOT}/logs"

# Runtime configuration
export LUCY_ROUTER_PY=1
export LUCY_EXEC_PY=1
export LUCY_LOCAL_MODEL=local-lucy-fast
export LUCY_OLLAMA_API_URL=http://127.0.0.1:11434/api/generate
export LUCY_ENABLE_INTERNET=1
export LUCY_SESSION_MEMORY=1

# GPU memory optimization: enable Flash Attention for Ollama
# Reduces VRAM usage for transformer attention without accuracy loss
export OLLAMA_FLASH_ATTENTION=1

# Force TTS (Kokoro) to CPU.
# With 1024 context (local-lucy-fast) + Whisper large-v3-turbo on GPU,
# VRAM is fully utilized (~11.2 GB / 12 GB).  Kokoro (~0.2 GB) does not fit
# reliably without causing CUDA OOM.  It runs fast via the persistent worker.
export LUCY_VOICE_KOKORO_DEVICE=cpu
export LUCY_VOICE_KOKORO_SPEED=1.2
export LUCY_VOICE_TTS_CHUNK_MAX_CHARS=400

# Voice STT (Whisper) library path
export LD_LIBRARY_PATH="${SCRIPT_DIR}/runtime/voice/whisper.cpp/build/src:${SCRIPT_DIR}/runtime/voice/whisper.cpp/build/ggml/src:${LD_LIBRARY_PATH:-}"

V8_PYTHON="${SCRIPT_DIR}/ui-v8/.venv/bin/python3"
if [ -x "$V8_PYTHON" ]; then
    export LUCY_VOICE_PYTHON_BIN="$V8_PYTHON"
    APP_PYTHON="$V8_PYTHON"
else
    APP_PYTHON="/usr/bin/python3"
fi

# =============================================================================
# STALE STATE SANITIZATION
# Cached state files can hold values from previous runs (e.g., tts_device,
# stt_backend) that conflict with current env vars. Clearing them on startup
# guarantees ground-truth detection on first use.
# =============================================================================

# Clear stale voice runtime cache (contains tts_device, stt_device, etc.)
_voice_runtime_file="${LUCY_VOICE_RUNTIME_FILE:-${LUCY_RUNTIME_NAMESPACE_ROOT}/state/voice_runtime.json}"
for _vr_candidate in \
    "${_voice_runtime_file}" \
    "${LUCY_RUNTIME_NAMESPACE_ROOT}/state/voice_runtime.json"
do
    if [ -f "${_vr_candidate}" ]; then
        rm -f "${_vr_candidate}"
    fi
done

# Clear stale semantic interpreter backend cache
for _si_candidate in \
    "${SCRIPT_DIR}/state/semantic_interpreter_backend.json" \
    "${LUCY_RUNTIME_NAMESPACE_ROOT}/state/semantic_interpreter_backend.json" \
    "${LUCY_RUNTIME_NAMESPACE_ROOT}/state/semantic_interpreter_backend.json"
do
    if [ -f "${_si_candidate}" ]; then
        rm -f "${_si_candidate}"
    fi
done

# Clear stale worker PID / socket files
rm -f "${LUCY_RUNTIME_NAMESPACE_ROOT}/tmp/run/whisper_worker.pid"
rm -f "${LUCY_RUNTIME_NAMESPACE_ROOT}/tmp/run/kokoro_tts_worker.sock"

# =============================================================================
# STARTUP VALIDATION
# =============================================================================

# Warn if current_state.json model conflicts with LUCY_LOCAL_MODEL env var.
# This is a common silent misconfiguration: the env says one thing, the
# persistent state file says another, and the state file wins at runtime.
_state_file="${LUCY_RUNTIME_NAMESPACE_ROOT}/state/current_state.json"
if [ -f "${_state_file}" ]; then
    _state_model=$(python3 -c "import sys,json; print(json.load(open('${_state_file}')).get('model',''))" 2>/dev/null || true)
    if [ -n "${_state_model}" ] && [ "${_state_model}" != "${LUCY_LOCAL_MODEL}" ]; then
        echo "[START_LUCY] WARNING: current_state.json model='${_state_model}' differs from LUCY_LOCAL_MODEL='${LUCY_LOCAL_MODEL}'"
        echo "[START_LUCY] The state file value will be used. Run: python3 tools/runtime_control.py set-model --value ${LUCY_LOCAL_MODEL}"
    fi
fi

# =============================================================================
# LAUNCH HMI
# =============================================================================
cd ui-v8
exec "$APP_PYTHON" -m app.main "$@"
