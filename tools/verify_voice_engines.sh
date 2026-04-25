#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${LUCY_ROOT:-$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)}"
WORKSPACE_ROOT="$(dirname -- "$(dirname -- "${ROOT}")")"
UI_ROOT="${LUCY_UI_ROOT:-${WORKSPACE_ROOT}/ui-v7}"
UI_VENV_PY="${UI_ROOT}/.venv/bin/python3"
TTS_ADAPTER="${ROOT}/tools/voice/tts_adapter.py"

INSTALL_PREFIX_RAW="${LUCY_VOICE_INSTALL_PREFIX:-runtime/voice}"
LUCY_VOICE_MODEL="${LUCY_VOICE_MODEL:-small.en}"

if [[ "${INSTALL_PREFIX_RAW}" = /* ]]; then
  INSTALL_PREFIX="${INSTALL_PREFIX_RAW}"
else
  INSTALL_PREFIX="${ROOT}/${INSTALL_PREFIX_RAW}"
fi

WHISPER_BIN="${INSTALL_PREFIX}/bin/whisper"
WHISPER_MODEL="${INSTALL_PREFIX}/models/ggml-${LUCY_VOICE_MODEL}.bin"
PIPER_BIN="${INSTALL_PREFIX}/bin/piper"
WHISPER_LIB_SRC="${INSTALL_PREFIX}/whisper.cpp/build/src"
WHISPER_GGML_LIB_SRC="${INSTALL_PREFIX}/whisper.cpp/build/ggml/src"

bundled_whisper_env(){
  local joined=""
  if [[ -d "${WHISPER_LIB_SRC}" ]]; then
    joined="${WHISPER_LIB_SRC}"
  fi
  if [[ -d "${WHISPER_GGML_LIB_SRC}" ]]; then
    joined="${joined:+${joined}:}${WHISPER_GGML_LIB_SRC}"
  fi
  if [[ -n "${joined}" && -n "${LD_LIBRARY_PATH:-}" ]]; then
    joined="${joined}:${LD_LIBRARY_PATH}"
  fi
  printf '%s' "${joined}"
}

die(){ echo "FAIL: $*" >&2; exit 1; }
ok(){ echo "OK: $*"; }
warn(){ echo "WARN: $*"; }

if [[ -x "${WHISPER_BIN}" ]]; then
  if LD_LIBRARY_PATH="$(bundled_whisper_env)" "${WHISPER_BIN}" -h >/dev/null 2>&1; then
    ok "whisper binary"
  else
    die "whisper binary unusable (${WHISPER_BIN})"
  fi
elif command -v whisper-cli >/dev/null 2>&1 || command -v whisper-cpp >/dev/null 2>&1; then
  ok "whisper binary (system)"
else
  die "whisper binary missing"
fi

if [[ -s "${WHISPER_MODEL}" ]]; then
  ok "whisper model"
else
  die "whisper model missing (${WHISPER_MODEL})"
fi

if [[ -x "${PIPER_BIN}" ]]; then
  ok "piper TTS"
elif command -v piper >/dev/null 2>&1; then
  ok "piper TTS (system)"
else
  warn "no TTS engine found"
fi

if command -v ffmpeg >/dev/null 2>&1 && command -v arecord >/dev/null 2>&1; then
  ok "audio tooling present"
else
  die "audio tooling missing (need ffmpeg and arecord)"
fi

if [[ ! -x "${UI_VENV_PY}" ]]; then
  die "ui-v7 python missing (${UI_VENV_PY})"
fi

if ! "${UI_VENV_PY}" -c 'import kokoro, soundfile' >/dev/null 2>&1; then
  die "ui-v7 kokoro stack missing (expected modules: kokoro, soundfile)"
fi
ok "ui-v7 kokoro modules present"

if [[ ! -f "${TTS_ADAPTER}" ]]; then
  die "tts adapter missing (${TTS_ADAPTER})"
fi
if ! payload="$("${UI_VENV_PY}" "${TTS_ADAPTER}" probe --engine kokoro 2>/dev/null || true)"; then
  die "kokoro probe failed to execute"
fi
if [[ "${payload}" != *'"ok": true'* ]] || [[ "${payload}" != *'"engine": "kokoro"'* ]]; then
  die "kokoro probe failed (${payload})"
fi
ok "kokoro probe (ui-v7) passes"
