#!/usr/bin/env bash
# ROLE: Voice push-to-talk wrapper - NOW DEFAULTS TO PYTHON
# This script defaults to Python voice runtime (router_py/voice_runtime.py).
# The shell implementation is deprecated; Python path is recommended.
# Set LUCY_VOICE_PY=0 to force legacy shell mode (not recommended).
set -euo pipefail

# Deprecation warning
if [[ "${LUCY_VOICE_PY:-1}" != "1" && "${LUCY_VOICE_PY_SILENCE_WARNING:-0}" != "1" ]]; then
  echo "[WARNING] Using legacy shell voice mode (deprecated)." >&2
  echo "  Unset LUCY_VOICE_PY or set LUCY_VOICE_PY=1 for Python voice runtime." >&2
  echo "  Set LUCY_VOICE_PY_SILENCE_WARNING=1 to suppress this warning." >&2
  echo >&2
fi
umask 077

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${LUCY_ROOT:-$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)}"
LUCY_WORKSPACE_ROOT="$(CDPATH= cd -- "${ROOT}/../.." && pwd)"
NL_CHAT_BIN="${LUCY_VOICE_NL_CHAT_BIN:-${ROOT}/tools/lucy_nl_chat.sh}"
TTS_ADAPTER="${ROOT}/tools/voice/tts_adapter.py"
TTS_PLAYBACK="${ROOT}/tools/voice/playback.py"
KOKORO_WORKER_TOOL="${ROOT}/tools/voice/kokoro_session_worker.py"

MAX_SECONDS="${LUCY_VOICE_MAX_SECONDS:-8}"
STT_ENGINE_REQ="${LUCY_VOICE_STT_ENGINE:-auto}"
TTS_ENGINE_REQ="${LUCY_VOICE_TTS_ENGINE:-auto}"
TTS_VOICE="${LUCY_VOICE_TTS_VOICE:-en_US}"
TTS_CLEAN="${LUCY_VOICE_TTS_CLEAN:-1}"
TTS_MAX_CHARS="${LUCY_VOICE_TTS_MAX_CHARS:-1000}"
PIPER_LENGTH_SCALE="${LUCY_VOICE_PIPER_LENGTH_SCALE:-}"
PIPER_NOISE_SCALE="${LUCY_VOICE_PIPER_NOISE_SCALE:-}"
PIPER_NOISE_W_SCALE="${LUCY_VOICE_PIPER_NOISE_W_SCALE:-}"
PIPER_SENTENCE_SILENCE="${LUCY_VOICE_PIPER_SENTENCE_SILENCE:-}"
PIPER_SPEAKER="${LUCY_VOICE_PIPER_SPEAKER:-}"
PIPER_PREPAD_MS="${LUCY_VOICE_PIPER_PREPAD_MS:-80}"
KOKORO_PREPAD_MS="${LUCY_VOICE_KOKORO_PREPAD_MS:-120}"
KOKORO_FIRST_CHUNK_PREPAD_MS="${LUCY_VOICE_KOKORO_FIRST_CHUNK_PREPAD_MS:-220}"
KOKORO_FIRST_CHUNK_PLAYER_PRIME_MS="${LUCY_VOICE_KOKORO_FIRST_CHUNK_PLAYER_PRIME_MS:-80}"
TTS_CHUNK_PAUSE_MS="${LUCY_VOICE_TTS_CHUNK_PAUSE_MS:-28}"
ONESHOT="${LUCY_VOICE_ONESHOT:-0}"
PTT_MODE="${LUCY_VOICE_PTT_MODE:-hold}"
PTT_HOLD_RELEASE_MS="${LUCY_VOICE_PTT_HOLD_RELEASE_MS:-700}"
VOICE_ROUTE_MODE="${LUCY_VOICE_ROUTE_MODE:-auto}"
VOICE_INSTALL_PREFIX_RAW="${LUCY_VOICE_INSTALL_PREFIX:-runtime/voice}"
VOICE_MODEL_NAME="${LUCY_VOICE_MODEL:-small.en}"
VOICE_PIPER_VOICE="${LUCY_VOICE_PIPER_VOICE:-en_GB-cori-high}"

if [[ "${VOICE_INSTALL_PREFIX_RAW}" = /* ]]; then
  VOICE_INSTALL_PREFIX="${VOICE_INSTALL_PREFIX_RAW}"
else
  VOICE_INSTALL_PREFIX="${ROOT}/${VOICE_INSTALL_PREFIX_RAW}"
fi
VOICE_BIN_DIR="${VOICE_INSTALL_PREFIX}/bin"
VOICE_MODEL_DIR="${VOICE_INSTALL_PREFIX}/models"

RUN_DIR="${ROOT}/tmp/run"
LOG_DIR="${ROOT}/tmp/logs"
VOICE_WAV="${RUN_DIR}/voice_input.wav"
VOICE_LOG="${LOG_DIR}/voice_session.log"
VOICE_SESSION_MEMORY="${LUCY_VOICE_SESSION_MEMORY:-1}"
VOICE_SESSION_MEMORY_FILE="${LUCY_VOICE_SESSION_MEMORY_FILE:-${RUN_DIR}/voice_session_memory_$$.txt}"

resolve_voice_python(){
  local candidate explicit preferred_engine payload detected_engine
  explicit="${LUCY_VOICE_PYTHON_BIN:-}"
  if [[ -n "${explicit}" && -x "${explicit}" ]]; then
    echo "${explicit}"
    return 0
  fi
  preferred_engine=""
  case "${TTS_ENGINE_REQ}" in
    auto|kokoro)
      preferred_engine="kokoro"
      ;;
  esac
  # ISOLATION: V8 only uses ui-v8, NEVER falls back to ui-v7
  candidate="${LUCY_WORKSPACE_ROOT}/ui-v8/.venv/bin/python3"
  if [[ ! -x "${candidate}" ]]; then
    echo "V8 ISOLATION VIOLATION: ui-v8 Python not found at ${candidate}. V8 cannot use V7 components." >&2
    return 1
  fi
  
  if [[ -n "${preferred_engine}" && -f "${TTS_ADAPTER}" ]]; then
    payload="$("${candidate}" "${TTS_ADAPTER}" probe --engine "${preferred_engine}" 2>/dev/null || true)"
    detected_engine="$(printf '%s' "${payload}" | sed -n 's/.*"engine": "\([^"]*\)".*/\1/p' | head -n 1)"
    if [[ "${detected_engine}" == "${preferred_engine}" ]]; then
      echo "${candidate}"
      return 0
    fi
  fi
  
  echo "${candidate}"
}

VOICE_PYTHON_BIN="$(resolve_voice_python)"

mkdir -p "${RUN_DIR}" "${LOG_DIR}"
touch "${VOICE_SESSION_MEMORY_FILE}"

if ! [[ "${MAX_SECONDS}" =~ ^[0-9]+$ ]] || [[ "${MAX_SECONDS}" -lt 1 ]]; then
  MAX_SECONDS=8
fi

if [[ ! -x "${NL_CHAT_BIN}" ]]; then
  echo "ERROR: missing executable: ${NL_CHAT_BIN}" >&2
  exit 2
fi

STT_ENGINE=""
STT_BIN=""
REC_ENGINE=""
REC_BIN=""
TTS_ENGINE="none"
TTS_BIN=""
REC_PID=""
KEYBOARD_FD="0"
VOICE_CONVERSATION_FORCE="${LUCY_CONVERSATION_MODE_FORCE:-0}"
KOKORO_WORKER_PID=""
KOKORO_WORKER_IN=""
KOKORO_WORKER_OUT=""
KOKORO_WORKER_PREWARM_PENDING=0

case "${VOICE_CONVERSATION_FORCE}" in
  1|true|yes|on) VOICE_CONVERSATION_FORCE="1" ;;
  *) VOICE_CONVERSATION_FORCE="0" ;;
esac

TMP_STT_PREFIX=""
TMP_STT_OUT=""
TMP_STT_ERR=""
STT_LAST_ERROR=""

cleanup(){
  if declare -F stop_kokoro_worker >/dev/null 2>&1; then
    stop_kokoro_worker
  fi
  if declare -F abort_first_sentence_tts >/dev/null 2>&1; then
    abort_first_sentence_tts
  fi
  if [[ -n "${REC_PID}" ]] && kill -0 "${REC_PID}" >/dev/null 2>&1; then
    kill -TERM "${REC_PID}" >/dev/null 2>&1 || true
    wait "${REC_PID}" >/dev/null 2>&1 || true
  fi
  rm -f "${VOICE_WAV}" >/dev/null 2>&1 || true
  if [[ -n "${TMP_STT_OUT}" ]]; then
    rm -f "${TMP_STT_OUT}" >/dev/null 2>&1 || true
  fi
  if [[ -n "${TMP_STT_ERR}" ]]; then
    rm -f "${TMP_STT_ERR}" >/dev/null 2>&1 || true
  fi
  if [[ -n "${TMP_STT_PREFIX}" ]]; then
    rm -f "${TMP_STT_PREFIX}.txt" >/dev/null 2>&1 || true
  fi
  if [[ "${KEYBOARD_FD}" != "0" ]]; then
    eval "exec ${KEYBOARD_FD}<&-"
  fi
  rm -f "${VOICE_SESSION_MEMORY_FILE}" >/dev/null 2>&1 || true
}
trap cleanup EXIT
trap 'echo; exit 0' INT TERM

log_event(){
  local transcript="$1"
  local status="$2"
  local ts
  ts="$(date -Is)"
  transcript="$(printf '%s' "${transcript}" | tr '\n\r' ' ' | sed -E 's/[[:space:]]+/ /g; s/^ +//; s/ +$//')"
  printf '%s stt=%s tts=%s status=%s transcript="%s"\n' \
    "${ts}" "${STT_ENGINE}" "${TTS_ENGINE}" "${status}" "${transcript}" >> "${VOICE_LOG}"
}

voice_memory_status(){
  local turns max_turns
  local state="off"
  max_turns="${LUCY_MEM_MAX_TURNS:-4}"
  if ! [[ "${max_turns}" =~ ^[0-9]+$ ]] || [[ "${max_turns}" -lt 1 ]]; then
    max_turns=4
  fi
  if [[ "${VOICE_SESSION_MEMORY}" == "1" ]]; then
    state="on"
  fi
  turns="$(grep -c '^User: ' "${VOICE_SESSION_MEMORY_FILE}" 2>/dev/null || true)"
  echo "Memory: ${state} turns=${turns}/${max_turns}"
}

voice_memory_clear(){
  : > "${VOICE_SESSION_MEMORY_FILE}"
  echo "Memory: cleared"
}

handle_voice_memory_command(){
  local raw cmd compact
  raw="$1"
  cmd="$(printf '%s' "${raw}" | tr '[:upper:]' '[:lower:]' | sed -E 's/^[[:space:]]+|[[:space:]]+$//g; s/[[:space:]]+/ /g')"
  compact="$(printf '%s' "${cmd}" | tr -d '[:space:][:punct:]')"
  case "${cmd}" in
    "/memory status"|"/memory show"|"memory status"|"memory show")
      voice_memory_status
      return 0
      ;;
    "/memory clear"|"memory clear")
      voice_memory_clear
      return 0
      ;;
    "/memory on"|"memory on")
      VOICE_SESSION_MEMORY="1"
      touch "${VOICE_SESSION_MEMORY_FILE}"
      echo "Memory: on"
      return 0
      ;;
    "/memory off"|"memory off")
      VOICE_SESSION_MEMORY="0"
      echo "Memory: off"
      return 0
      ;;
  esac
  case "${compact}" in
    memorystatus|memoryshow)
      voice_memory_status
      return 0
      ;;
    memoryclear)
      voice_memory_clear
      return 0
      ;;
    memoryon)
      VOICE_SESSION_MEMORY="1"
      touch "${VOICE_SESSION_MEMORY_FILE}"
      echo "Memory: on"
      return 0
      ;;
    memoryoff)
      VOICE_SESSION_MEMORY="0"
      echo "Memory: off"
      return 0
      ;;
  esac
  return 1
}

map_spoken_command(){
  local raw n
  raw="$1"
  n="$(printf '%s' "${raw}" | tr '[:upper:]' '[:lower:]' | sed -E 's/^[[:space:]]+|[[:space:]]+$//g; s/[[:space:]]+/ /g')"

  case "${n}" in
    "forward slash online"|"slash online") printf '%s' "/mode online"; return 0 ;;
    "forward slash offline"|"slash offline") printf '%s' "/mode offline"; return 0 ;;
    "forward slash auto"|"slash auto") printf '%s' "/mode auto"; return 0 ;;
    "conversation on") printf '%s' "/conversation on"; return 0 ;;
    "conversation off") printf '%s' "/conversation off"; return 0 ;;
    "memory status"|"memory show") printf '%s' "/memory status"; return 0 ;;
    "memory clear") printf '%s' "/memory clear"; return 0 ;;
    "memory on") printf '%s' "/memory on"; return 0 ;;
    "memory off") printf '%s' "/memory off"; return 0 ;;
    "quit voice"|"exit voice") printf '%s' "q"; return 0 ;;
  esac

  printf '%s' "${raw}"
}

handle_voice_session_command(){
  local raw cmd
  raw="$1"
  cmd="$(printf '%s' "${raw}" | tr '[:upper:]' '[:lower:]' | sed -E 's/^[[:space:]]+|[[:space:]]+$//g; s/[[:space:]]+/ /g')"

  case "${cmd}" in
    q|quit|/quit|/exit|/back|quit\ voice|exit\ voice)
      return 10
      ;;
    /mode\ online|mode\ online)
      VOICE_ROUTE_MODE="online"
      echo "Mode: online"
      return 0
      ;;
    /mode\ offline|mode\ offline)
      VOICE_ROUTE_MODE="offline"
      echo "Mode: offline"
      return 0
      ;;
    /mode\ auto|mode\ auto)
      VOICE_ROUTE_MODE="auto"
      echo "Mode: auto"
      return 0
      ;;
    /conversation\ on|conversation\ on)
      VOICE_CONVERSATION_FORCE="1"
      echo "Conversation mode: on"
      return 0
      ;;
    /conversation\ off|conversation\ off)
      VOICE_CONVERSATION_FORCE="0"
      echo "Conversation mode: off"
      return 0
      ;;
  esac

  if handle_voice_memory_command "${raw}"; then
    return 0
  fi
  return 1
}

pick_recorder(){
  if command -v arecord >/dev/null 2>&1; then
    REC_ENGINE="arecord"
    REC_BIN="$(command -v arecord)"
    return 0
  fi
  if command -v pw-record >/dev/null 2>&1; then
    REC_ENGINE="pw-record"
    REC_BIN="$(command -v pw-record)"
    return 0
  fi
  echo "ERROR: no local recorder detected (need arecord or pw-record)" >&2
  exit 1
}

now_ms(){
  local ms
  ms="$(date +%s%3N 2>/dev/null || true)"
  if [[ "${ms}" =~ ^[0-9]+$ ]]; then
    printf '%s' "${ms}"
  else
    printf '%s000' "$(date +%s)"
  fi
}

canonical_path(){
  local raw="$1"
  if command -v readlink >/dev/null 2>&1; then
    readlink -f -- "${raw}" 2>/dev/null || printf '%s' "${raw}"
  else
    printf '%s' "${raw}"
  fi
}

whisper_ld_library_path(){
  local whisper_bin="$1"
  local bundled_bin whisper_lib ggml_lib joined=""
  bundled_bin="${VOICE_BIN_DIR}/whisper"
  if [[ -z "${whisper_bin}" || ! -e "${whisper_bin}" || ! -e "${bundled_bin}" ]]; then
    return 0
  fi
  if [[ "$(canonical_path "${whisper_bin}")" != "$(canonical_path "${bundled_bin}")" ]]; then
    return 0
  fi
  whisper_lib="${VOICE_INSTALL_PREFIX}/whisper.cpp/build/src"
  ggml_lib="${VOICE_INSTALL_PREFIX}/whisper.cpp/build/ggml/src"
  if [[ -d "${whisper_lib}" ]]; then
    joined="${whisper_lib}"
  fi
  if [[ -d "${ggml_lib}" ]]; then
    joined="${joined:+${joined}:}${ggml_lib}"
  fi
  if [[ -n "${joined}" && -n "${LD_LIBRARY_PATH:-}" ]]; then
    joined="${joined}:${LD_LIBRARY_PATH}"
  fi
  printf '%s' "${joined}"
}

first_nonempty_file_line(){
  local path="$1"
  [[ -s "${path}" ]] || return 1
  awk 'NF { print; exit }' "${path}"
}

init_keyboard_input(){
  # Prefer a dedicated terminal FD so key reads remain stable across subprocesses.
  if [[ -r /dev/tty ]]; then
    if exec {KEYBOARD_FD}</dev/tty 2>/dev/null; then
      return 0
    fi
  fi
  KEYBOARD_FD="0"
}

drain_keyboard_buffer(){
  local _k=""
  while IFS= read -r -s -n1 -t 0.001 -u "${KEYBOARD_FD}" _k; do :; done
}

exit_oneshot(){
  drain_keyboard_buffer
  exit "${1:-0}"
}

start_recorder_bg(){
  rm -f "${VOICE_WAV}" >/dev/null 2>&1 || true
  case "${REC_ENGINE}" in
    arecord)
      "${REC_BIN}" -q -f S16_LE -r 16000 -c 1 "${VOICE_WAV}" >/dev/null 2>&1 &
      ;;
    pw-record)
      "${REC_BIN}" --channels 1 --rate 16000 --format s16 "${VOICE_WAV}" >/dev/null 2>&1 &
      ;;
    *)
      return 1
      ;;
  esac
  REC_PID="$!"
  return 0
}

stop_recorder_bg(){
  if [[ -n "${REC_PID}" ]] && kill -0 "${REC_PID}" >/dev/null 2>&1; then
    kill -INT "${REC_PID}" >/dev/null 2>&1 || true
    sleep 0.10
    if kill -0 "${REC_PID}" >/dev/null 2>&1; then
      kill -TERM "${REC_PID}" >/dev/null 2>&1 || true
    fi
    wait "${REC_PID}" >/dev/null 2>&1 || true
  fi
  REC_PID=""
}

pick_stt(){
  local req="${STT_ENGINE_REQ}"
  local whisper_bin="${LUCY_VOICE_WHISPER_BIN:-}"
  local vosk_bin="${LUCY_VOICE_VOSK_BIN:-}"

  if [[ -z "${whisper_bin}" ]]; then
    if [[ -x "${VOICE_BIN_DIR}/whisper" ]]; then
      whisper_bin="${VOICE_BIN_DIR}/whisper"
    elif command -v whisper >/dev/null 2>&1; then
      whisper_bin="$(command -v whisper)"
    elif command -v whisper-cli >/dev/null 2>&1; then
      whisper_bin="$(command -v whisper-cli)"
    elif command -v whisper-cpp >/dev/null 2>&1; then
      whisper_bin="$(command -v whisper-cpp)"
    fi
  fi

  if [[ -z "${vosk_bin}" ]]; then
    if command -v vosk-transcriber >/dev/null 2>&1; then
      vosk_bin="$(command -v vosk-transcriber)"
    fi
  fi

  case "${req}" in
    auto)
      if [[ -n "${whisper_bin}" ]]; then
        STT_ENGINE="whisper"
        STT_BIN="${whisper_bin}"
        return 0
      fi
      if [[ -n "${vosk_bin}" ]]; then
        STT_ENGINE="vosk"
        STT_BIN="${vosk_bin}"
        return 0
      fi
      ;;
    whisper)
      if [[ -n "${whisper_bin}" ]]; then
        STT_ENGINE="whisper"
        STT_BIN="${whisper_bin}"
        return 0
      fi
      ;;
    vosk)
      if [[ -n "${vosk_bin}" ]]; then
        STT_ENGINE="vosk"
        STT_BIN="${vosk_bin}"
        return 0
      fi
      ;;
  esac

  echo "ERROR: no local STT engine detected" >&2
  exit 1
}

pick_tts(){
  local req="${TTS_ENGINE_REQ}"
  local payload engine
  if [[ ! -f "${TTS_ADAPTER}" ]] || [[ -z "${VOICE_PYTHON_BIN}" ]] || [[ ! -x "${VOICE_PYTHON_BIN}" ]]; then
    TTS_ENGINE="none"
    TTS_BIN=""
    return 0
  fi
  payload="$("${VOICE_PYTHON_BIN}" "${TTS_ADAPTER}" probe --engine "${req}" 2>/dev/null || true)"
  engine="$(tts_json_field "${payload}" engine || true)"
  case "${engine}" in
    piper|kokoro)
      TTS_ENGINE="${engine}"
      TTS_BIN="${engine}"
      ;;
    *)
      TTS_ENGINE="none"
      TTS_BIN=""
      ;;
  esac
  return 0
}

stop_kokoro_worker(){
  if [[ -n "${KOKORO_WORKER_IN}" ]]; then
    eval "exec ${KOKORO_WORKER_IN}>&-"
  fi
  if [[ -n "${KOKORO_WORKER_OUT}" ]]; then
    eval "exec ${KOKORO_WORKER_OUT}<&-"
  fi
  if [[ -n "${KOKORO_WORKER_PID}" ]] && kill -0 "${KOKORO_WORKER_PID}" >/dev/null 2>&1; then
    kill -TERM "${KOKORO_WORKER_PID}" >/dev/null 2>&1 || true
    wait "${KOKORO_WORKER_PID}" >/dev/null 2>&1 || true
  fi
  KOKORO_WORKER_PID=""
  KOKORO_WORKER_IN=""
  KOKORO_WORKER_OUT=""
  KOKORO_WORKER_PREWARM_PENDING=0
}

kokoro_worker_build_request(){
  local cmd="$1"
  local text="${2:-}"
  local output_dir="${3:-}"
  KOKORO_WORKER_CMD="${cmd}" \
  KOKORO_WORKER_TEXT="${text}" \
  KOKORO_WORKER_OUTPUT_DIR="${output_dir}" \
  KOKORO_WORKER_ENGINE="${TTS_ENGINE_REQ}" \
  "${VOICE_PYTHON_BIN}" - <<'PY'
import json
import os

payload = {
    "cmd": os.environ.get("KOKORO_WORKER_CMD", ""),
    "engine": os.environ.get("KOKORO_WORKER_ENGINE", "") or "auto",
}
text = os.environ.get("KOKORO_WORKER_TEXT", "")
if text:
    payload["text"] = text
output_dir = os.environ.get("KOKORO_WORKER_OUTPUT_DIR", "")
if output_dir:
    payload["output_dir"] = output_dir
print(json.dumps(payload, sort_keys=True))
PY
}

kokoro_worker_send_request(){
  local cmd="$1"
  local text="${2:-}"
  local output_dir="${3:-}"
  local payload=""
  [[ -n "${KOKORO_WORKER_PID}" && -n "${KOKORO_WORKER_IN}" ]] || return 1
  payload="$(kokoro_worker_build_request "${cmd}" "${text}" "${output_dir}")" || return 1
  printf '%s\n' "${payload}" >&"${KOKORO_WORKER_IN}" || return 1
}

kokoro_worker_read_response(){
  local response=""
  [[ -n "${KOKORO_WORKER_PID}" && -n "${KOKORO_WORKER_OUT}" ]] || return 1
  if ! IFS= read -r -u "${KOKORO_WORKER_OUT}" response; then
    return 1
  fi
  printf '%s' "${response}"
}

flush_kokoro_worker_prewarm(){
  local _response=""
  if [[ "${KOKORO_WORKER_PREWARM_PENDING}" != "1" ]]; then
    return 0
  fi
  _response="$(kokoro_worker_read_response || true)"
  KOKORO_WORKER_PREWARM_PENDING=0
  [[ -n "${_response}" ]]
}

start_kokoro_worker(){
  [[ "${TTS_ENGINE}" == "kokoro" ]] || return 0
  [[ -f "${KOKORO_WORKER_TOOL}" && -x "${VOICE_PYTHON_BIN}" ]] || return 0
  if [[ -n "${KOKORO_WORKER_PID}" ]] && kill -0 "${KOKORO_WORKER_PID}" >/dev/null 2>&1; then
    return 0
  fi
  # Keep Kokoro in one long-lived Python process so pipeline/model caches survive.
  coproc KOKORO_TTS_WORKER { "${VOICE_PYTHON_BIN}" "${KOKORO_WORKER_TOOL}" 2>/dev/null; }
  KOKORO_WORKER_OUT="${KOKORO_TTS_WORKER[0]}"
  KOKORO_WORKER_IN="${KOKORO_TTS_WORKER[1]}"
  KOKORO_WORKER_PID="${KOKORO_TTS_WORKER_PID:-}"
  if [[ -n "${KOKORO_WORKER_PID}" ]]; then
    if kokoro_worker_send_request "prewarm"; then
      KOKORO_WORKER_PREWARM_PENDING=1
    fi
  fi
}

kokoro_worker_synthesize(){
  local text="$1"
  local response=""
  [[ "${TTS_ENGINE}" == "kokoro" ]] || return 1
  [[ -n "${KOKORO_WORKER_PID}" ]] || return 1
  flush_kokoro_worker_prewarm >/dev/null 2>&1 || true
  kokoro_worker_send_request "synthesize" "${text}" "${RUN_DIR}" || return 1
  response="$(kokoro_worker_read_response)" || return 1
  printf '%s' "${response}"
}

record_wav(){
  rm -f "${VOICE_WAV}" >/dev/null 2>&1 || true
  case "${REC_ENGINE}" in
    arecord)
      "${REC_BIN}" -q -f S16_LE -r 16000 -c 1 -d "${MAX_SECONDS}" "${VOICE_WAV}" >/dev/null 2>&1
      ;;
    pw-record)
      "${REC_BIN}" --channels 1 --rate 16000 --format s16 --duration "${MAX_SECONDS}" "${VOICE_WAV}" >/dev/null 2>&1
      ;;
    *)
      return 1
      ;;
  esac
  [[ -s "${VOICE_WAV}" ]]
}

record_wav_hold_space(){
  local key=""
  local last_ms now elapsed

  if ! [[ "${PTT_HOLD_RELEASE_MS}" =~ ^[0-9]+$ ]] || [[ "${PTT_HOLD_RELEASE_MS}" -lt 100 ]]; then
    PTT_HOLD_RELEASE_MS=700
  fi

  drain_keyboard_buffer

  # Wait for initial space key press.
  while true; do
    if ! IFS= read -r -s -n1 -u "${KEYBOARD_FD}" key; then
      return 1
    fi
    if [[ "${key}" == " " ]]; then
      break
    fi
    if [[ "${key}" == "q" || "${key}" == "Q" ]]; then
      return 2
    fi
  done

  # Start recording only after explicit PTT press.
  start_recorder_bg || return 1

  # Hold-to-talk using keyboard auto-repeat: while space repeats, keep recording.
  last_ms="$(now_ms)"
  while true; do
    if IFS= read -r -s -n1 -t 0.05 -u "${KEYBOARD_FD}" key; then
      if [[ "${key}" == " " ]]; then
        last_ms="$(now_ms)"
      fi
    fi
    now="$(now_ms)"
    elapsed=$((now - last_ms))
    if (( elapsed >= PTT_HOLD_RELEASE_MS )); then
      break
    fi
  done

  stop_recorder_bg
  [[ -s "${VOICE_WAV}" ]]
}

stt_whisper(){
  local wav="$1"
  local model="${LUCY_VOICE_WHISPER_MODEL:-${VOICE_MODEL_DIR}/ggml-${VOICE_MODEL_NAME}.bin}"
  local lang="${LUCY_VOICE_STT_LANG:-auto}"
  local out=""
  local whisper_ld_path=""
  local whisper_rc=0

  if [[ ! -s "${model}" && -s "${ROOT}/models/ggml-base.bin" ]]; then
    model="${ROOT}/models/ggml-base.bin"
  fi

  TMP_STT_PREFIX="${RUN_DIR}/voice_whisper_$$"
  TMP_STT_OUT="${RUN_DIR}/voice_whisper_stdout_$$.txt"
  TMP_STT_ERR="${RUN_DIR}/voice_whisper_stderr_$$.txt"
  rm -f "${TMP_STT_PREFIX}.txt" "${TMP_STT_OUT}" "${TMP_STT_ERR}" >/dev/null 2>&1 || true
  whisper_ld_path="$(whisper_ld_library_path "${STT_BIN}")"

  if [[ "${lang}" == "auto" ]]; then
    if [[ -n "${whisper_ld_path}" ]]; then
      LD_LIBRARY_PATH="${whisper_ld_path}" "${STT_BIN}" -m "${model}" -f "${wav}" -otxt -of "${TMP_STT_PREFIX}" > "${TMP_STT_OUT}" 2> "${TMP_STT_ERR}" || whisper_rc=$?
    else
      "${STT_BIN}" -m "${model}" -f "${wav}" -otxt -of "${TMP_STT_PREFIX}" > "${TMP_STT_OUT}" 2> "${TMP_STT_ERR}" || whisper_rc=$?
    fi
  else
    if [[ -n "${whisper_ld_path}" ]]; then
      LD_LIBRARY_PATH="${whisper_ld_path}" "${STT_BIN}" -m "${model}" -f "${wav}" -l "${lang}" -otxt -of "${TMP_STT_PREFIX}" > "${TMP_STT_OUT}" 2> "${TMP_STT_ERR}" || whisper_rc=$?
    else
      "${STT_BIN}" -m "${model}" -f "${wav}" -l "${lang}" -otxt -of "${TMP_STT_PREFIX}" > "${TMP_STT_OUT}" 2> "${TMP_STT_ERR}" || whisper_rc=$?
    fi
  fi

  if [[ "${whisper_rc}" != "0" ]]; then
    STT_LAST_ERROR="$(first_nonempty_file_line "${TMP_STT_ERR}" || first_nonempty_file_line "${TMP_STT_OUT}" || printf 'whisper exited with status %s' "${whisper_rc}")"
    printf ''
    return 0
  fi

  if [[ -s "${TMP_STT_PREFIX}.txt" ]]; then
    out="$(cat "${TMP_STT_PREFIX}.txt")"
  elif [[ -s "${TMP_STT_OUT}" ]]; then
    out="$(cat "${TMP_STT_OUT}")"
  fi

  printf '%s' "${out}" | tr '\n\r' ' ' | sed -E 's/[[:space:]]+/ /g; s/^ +//; s/ +$//'
}

stt_vosk(){
  local wav="$1"
  local out=""

  TMP_STT_OUT="${RUN_DIR}/voice_vosk_stdout_$$.txt"
  rm -f "${TMP_STT_OUT}" >/dev/null 2>&1 || true

  out="$("${STT_BIN}" -i "${wav}" 2>/dev/null || true)"
  if [[ -z "${out}" ]]; then
    out="$("${STT_BIN}" "${wav}" 2>/dev/null || true)"
  fi
  printf '%s' "${out}" | tr '\n\r' ' ' | sed -E 's/[[:space:]]+/ /g; s/^ +//; s/ +$//'
}

transcribe(){
  local wav="$1"
  STT_LAST_ERROR=""
  case "${STT_ENGINE}" in
    whisper) stt_whisper "${wav}" ;;
    vosk) stt_vosk "${wav}" ;;
    *) printf '' ;;
  esac
}

normalize_transcript(){
  local t="$1"
  printf '%s' "${t}" \
  | tr '\n\r' ' ' \
  | sed -E \
      -e 's/\[(blank_audio|inaudible|silence|no_speech|no speech)\]//I' \
      -e 's/(\(speaking in foreign language\)|\[speaking in foreign language\])[[:space:]]*//Ig' \
      -e 's/^[[:space:]]*(\((cough|coughing|sneeze|sneezing|sniff|sniffing|sigh|sighs|hmm|mmm|breath|breathing|laugh|laughter|noise|music|silence|inaudible|clears throat)[[:alpha:][:space:]_-]*\)|\[(cough|coughing|sneeze|sneezing|sniff|sniffing|sigh|sighs|hmm|mmm|breath|breathing|laugh|laughter|noise|music|silence|inaudible|clears throat)[[:alpha:][:space:]_-]*\])[[:space:]]*//I' \
      -e 's/\btin[[:space:]]+tuner\b/tinned tuna/Ig' \
      -e 's/\btin[[:space:]]+tuna\b/tinned tuna/Ig' \
      -e 's/\b([Rr][Aa]([Kk][Hh]?|[Cc][Hh]?|[Hh])[Aa]?[Ee]?[Ll]([Ii]|[Yy]|[Ee])|[Rr][Aa][Kk][Hh][Ii][Rr][Ii]|[Rr][Aa][Hh][Aa][Ll][Ii]|[Rr][Aa][Cc][Hh][Aa][Ee][Ll][Ii])\b/racheli/g' \
      -e 's/[[:space:]]+/ /g; s/^ +//; s/ +$//'
}

last_pet_food_from_voice_memory(){
  local f="${VOICE_SESSION_MEMORY_FILE:-}"
  [[ -n "${f}" && -s "${f}" ]] || return 1
  grep -E '^User: ' "${f}" 2>/dev/null \
    | tail -n 8 \
    | tr '[:upper:]' '[:lower:]' \
    | sed -E 's/[^a-z0-9 ]+/ /g; s/[[:space:]]+/ /g' \
    | awk '
      {
        for (i=1; i<=NF; i++) {
          if ($i ~ /^(tuna|salmon|chicken|beef|pork|turkey|rice|egg|eggs|bread|milk|cheese|yogurt|apple|banana|grape|grapes|raisin|raisins|onion|onions|garlic|chocolate|xylitol)$/) {
            last=$i
          }
        }
      }
      END { if (last != "") print last }
    '
}

last_pet_name_from_voice_memory(){
  local f="${VOICE_SESSION_MEMORY_FILE:-}"
  local name=""
  [[ -n "${f}" && -s "${f}" ]] || return 1
  name="$(
    grep -E '^User: ' "${f}" 2>/dev/null \
      | tail -n 20 \
      | sed -nE "s/^User: .*my dog is[[:space:]]+([A-Za-z][A-Za-z'-]{1,30}).*$/\\1/ip; s/^User: .*my dog's name is[[:space:]]+([A-Za-z][A-Za-z'-]{1,30}).*$/\\1/ip" \
      | tail -n 1
  )"
  [[ -n "${name}" ]] || return 1
  printf '%s' "${name}"
}

is_recent_pet_feeding_context(){
  local f="${VOICE_SESSION_MEMORY_FILE:-}"
  [[ -n "${f}" && -s "${f}" ]] || return 1
  grep -E '^User: ' "${f}" 2>/dev/null \
    | tail -n 6 \
    | tr '[:upper:]' '[:lower:]' \
    | sed -E 's/[[:space:]]+/ /g' \
    | grep -Eqi '(dog|dogs|cat|cats|pet|pets|oscar).*(safe to feed|safe for|safe to give|toxic|can .* eat|feed )|(safe to feed|safe for|safe to give|toxic|can .* eat|feed ).*(dog|dogs|cat|cats|pet|pets|oscar)'
}

rewrite_implicit_pet_feed_query(){
  local q="$1"
  local qn food pet_name detail
  qn="$(printf '%s' "${q}" | tr '[:upper:]' '[:lower:]' | sed -E 's/[[:space:]]+/ /g; s/^ +| +$//g')"

  # If this is a pet food safety question but missing explicit pet tokens,
  # expand subject from voice memory so router classifies as high-risk.
  if printf '%s' "${qn}" | grep -Eqi '(safe to feed|safe for|safe to give|toxic|poison|poisonous|can[[:space:]]+.*eat)'; then
    if ! printf '%s' "${qn}" | grep -Eqi '(^|[^[:alnum:]_])(dog|dogs|cat|cats|pet|pets|puppy|puppies|kitten|kittens)([^[:alnum:]_]|$)'; then
      if printf '%s' "${qn}" | grep -Eqi '(^|[^[:alnum:]_])oscar([^[:alnum:]_]|$)'; then
        q="$(printf '%s' "${q}" | sed -E 's/\b([Oo]scar)\b/my dog \1/g')"
      fi
      pet_name="$(last_pet_name_from_voice_memory || true)"
      if [[ -n "${pet_name}" ]]; then
        if printf '%s' "${qn}" | grep -Eqi '(^|[^[:alnum:]_])to[[:space:]]+oscar([^[:alnum:]_]|$)'; then
          q="$(printf '%s' "${q}" | sed -E "s/[Tt]o[[:space:]]+Oscar/to my dog ${pet_name}/g")"
        elif printf '%s' "${qn}" | grep -Eqi '(^|[^[:alnum:]_])(him|her)([^[:alnum:]_]|$)'; then
          q="$(printf '%s' "${q}" | sed -E "s/([Hh]im|[Hh]er)/my dog ${pet_name}/")"
        fi
      fi
    fi
  fi

  # Follow-up food question in active pet-feeding thread:
  # "What about tinned tuna, in olive oil or in brine?"
  # -> "Is tinned tuna, in olive oil or in brine safe to feed to my dog Oscar?"
  if printf '%s' "${qn}" | grep -Eqi '^what about ' \
    && printf '%s' "${qn}" | grep -Eqi '(tuna|salmon|chicken|beef|pork|turkey|rice|egg|eggs|bread|milk|cheese|yogurt|apple|banana|grape|grapes|raisin|raisins|onion|onions|garlic|chocolate|xylitol)' \
    && ! printf '%s' "${qn}" | grep -Eqi '(^|[^[:alnum:]_])(dog|dogs|cat|cats|pet|pets|puppy|puppies|kitten|kittens)([^[:alnum:]_]|$)'; then
    pet_name="$(last_pet_name_from_voice_memory || true)"
    if [[ -n "${pet_name}" ]]; then
      detail="$(printf '%s' "${q}" | sed -E 's/^[Ww]hat about[[:space:]]+//; s/[[:space:]]*[?]+[[:space:]]*$//')"
      q="Is ${detail} safe to feed to my dog ${pet_name}?"
    fi
  fi

  # Disfluent follow-up in an active pet-feeding thread:
  # "It's tinned tuna ... sorry ..."
  # -> "Is tinned tuna safe to feed to my dog <name>?"
  if printf '%s' "${qn}" | grep -Eqi '(tuna|salmon|chicken|beef|pork|turkey|rice|egg|eggs|bread|milk|cheese|yogurt|apple|banana|grape|grapes|raisin|raisins|onion|onions|garlic|chocolate|xylitol)' \
    && ! printf '%s' "${qn}" | grep -Eqi '(safe to feed|safe for|safe to give|toxic|poison|poisonous|can[[:space:]]+.*eat|feed[[:space:]]+)' \
    && ! printf '%s' "${qn}" | grep -Eqi '(^|[^[:alnum:]_])(dog|dogs|cat|cats|pet|pets|puppy|puppies|kitten|kittens)([^[:alnum:]_]|$)'; then
    pet_name="$(last_pet_name_from_voice_memory || true)"
    if [[ -n "${pet_name}" ]]; then
      detail="$(printf '%s' "${q}" | sed -E 's/[[:space:]]+/ /g; s/^ +| +$//g' \
        | sed -E 's/\b(it'"'"'s|it is|uh|umm|um|hmm|mmm|sorry)\b//Ig; s/[[:space:]]+/ /g; s/^ +| +$//g' \
        | sed -E 's/[[:space:]]*,[[:space:]]*/ /g; s/[[:space:]]*\.+[[:space:]]*/ /g; s/[[:space:]]+/ /g; s/^ +| +$//g')"
      [[ -n "${detail}" ]] || detail="tuna"
      q="Is ${detail} safe to feed to my dog ${pet_name}?"
    fi
  fi

  qn="$(printf '%s' "${q}" | tr '[:upper:]' '[:lower:]' | sed -E 's/[[:space:]]+/ /g; s/^ +| +$//g')"
  if printf '%s' "${qn}" | grep -Eq '^is it safe to feed( (to )?(him|her|oscar))?[?]?$'; then
    food="$(last_pet_food_from_voice_memory || true)"
    if [[ -n "${food}" ]]; then
      pet_name="$(last_pet_name_from_voice_memory || true)"
      if [[ -n "${pet_name}" ]]; then
        printf 'Is it safe to feed %s to my dog %s?' "${food}" "${pet_name}"
      else
        printf 'Is it safe to feed %s to Oscar?' "${food}"
      fi
      return 0
    fi
  fi
  printf '%s' "${q}"
}

trim_transcript_hallucinated_prefix(){
  local t="$1"
  printf '%s' "${t}" | awk '
    {
      text=$0
      gsub(/[[:space:]]+/, " ", text)
      sub(/^ /, "", text); sub(/ $/, "", text)
      if (length(text) == 0) { print text; next }

      n=split(text, raw, /[.!?]+[[:space:]]*/)
      m=0
      for (i=1; i<=n; i++) {
        s=raw[i]
        gsub(/^[[:space:]]+|[[:space:]]+$/, "", s)
        if (length(s) > 0) { m++; seg[m]=s }
      }
      if (m < 2) { print text; next }

      repeated_prefix=0
      noisy_prefix=0
      for (i=1; i<m; i++) {
        k=tolower(seg[i])
        gsub(/[^[:alnum:] ]/, "", k)
        gsub(/[[:space:]]+/, " ", k)
        sub(/^ /, "", k); sub(/ $/, "", k)
        if (length(k) == 0) continue
        seen[k]++
        if (seen[k] >= 2) repeated_prefix=1
        if (k ~ /(what do i say|i dont know|oscar|okay|ok)/) noisy_prefix=1
      }

      last=seg[m]
      lk=tolower(last)
      gsub(/[^[:alnum:] ]/, "", lk)
      gsub(/[[:space:]]+/, " ", lk)
      sub(/^ /, "", lk); sub(/ $/, "", lk)
      wc=split(lk, words, /[[:space:]]+/)
      is_clear_tail=(lk ~ /^(hi|hello|hey|good (morning|afternoon|evening))( |$)/ || lk ~ /how are you/)

      if (repeated_prefix && noisy_prefix && is_clear_tail && wc >= 3) {
        endp="."
        if (text ~ /\?[[:space:]]*$/) endp="?"
        else if (text ~ /![[:space:]]*$/) endp="!"
        print last endp
        next
      }
      print text
    }
  '
}

is_blank_transcript(){
  local t="$1"
  local n
  n="$(printf '%s' "${t}" | tr '[:upper:]' '[:lower:]' | sed -E 's/^[[:space:]]+|[[:space:]]+$//g')"
  [[ -z "${n}" ]] && return 0
  case "${n}" in
    "[blank_audio]"|"[silence]"|"[inaudible]"|"[no_speech]"|"[no speech]")
      return 0
      ;;
  esac
  return 1
}

extract_answer_block(){
  local raw="$1"
  local txt
  txt="$(printf '%s\n' "${raw}" | sed -E 's/^lucy> //')"
  printf '%s\n' "${txt}" | awk '
    /^Answer:[[:space:]]*$/ {in_block=1; next}
    /^Answer:[[:space:]]*.+$/ {
      line=$0
      sub(/^Answer:[[:space:]]*/, "", line)
      if (length(line) > 0) print line
      in_block=1
      next
    }
    in_block && /^(Claims|Citations|Evidence|Trust|Cache):/ {exit}
    in_block && /^lucy>[[:space:]]*/ {exit}
    in_block {print}
  '
}

shape_voice_answer_block(){
  local raw="$1"
  printf '%s\n' "${raw}" | sed -E \
    -e 's/[[:space:]]+(Key items:)/\
\1/g' \
    -e 's/[[:space:]]+(Sources:|Claims:|Citations:|Evidence:|Trust:|Cache:|Conflicts\/uncertainty:)/\
\1/g' \
    -e 's/[[:space:]]+-[[:space:]]+\[/\
- [/g' \
  | awk '
    BEGIN { in_key=0; bullets=0 }
    /^BEGIN_VALIDATED$/ || /^END_VALIDATED$/ { next }
    /^(Claims|Citations|Evidence|Trust|Cache):/ { exit }
    /^Conflicts\/uncertainty:/ { next }
    /^Summary:[[:space:]]*/ {
      sub(/^Summary:[[:space:]]*/, "", $0)
      if (length($0) > 0) print
      next
    }
    /^Key items:[[:space:]]*$/ {
      in_key=1
      print "Key items:"
      next
    }
    /^[[:space:]]*-[[:space:]]+/ {
      line=$0
      # Drop obviously truncated bullets (common when upstream answer is clipped).
      if (line ~ /^[[:space:]]*-[[:space:]]*\[[^]]*\.\.\./) next
      if (line ~ /^[[:space:]]*-[[:space:]]*[^[:space:]].*\.\.\.$/ && line !~ /[.!?]["'"'"'”’)]*$/) next
      sub(/^[[:space:]]*-[[:space:]]+\[[^]]+\][[:space:]]*\([^)]*\):[[:space:]]*/, "- ", line)
      sub(/^[[:space:]]*-[[:space:]]+\[[^]]+\][[:space:]]*:[[:space:]]*/, "- ", line)
      if (in_key) {
        bullets++
        if (bullets > 10) next
      }
      print line
      next
    }
    { print }
  ' | sed -E \
      -e 's/[[:space:]]+as of[[:space:]]+[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.+-]+Z?\.?/. /I' \
      -e 's/[[:space:]]+as of[[:space:]]+[A-Z][a-z]{2},?[[:space:]]+[0-9]{1,2}[[:space:]]+[A-Z][a-z]{2}[[:space:]]+[0-9]{4}[[:space:]]+[0-9:]{4,8}([[:space:]]+[+-][0-9]{4})?\.?/. /I' \
      -e 's/-[[:space:]]+\[[^]]+\][[:space:]]*\([^)]*\):[[:space:]]*/- /g' \
      -e 's/-[[:space:]]+\[[^]]+\][[:space:]]*:[[:space:]]*/- /g' \
      -e 's/[[:space:]]+\.[[:space:]]+\./. /g' \
      -e '/^[[:space:]]*$/N;/^\n$/D' \
      -e 's/[[:space:]]+$//'
}

extract_first_nl_answer(){
  local raw="$1"
  printf '%s\n' "${raw}" | awk '
    BEGIN { seen_prompt=0; capturing=0 }
    /^lucy> / {
      line=$0
      sub(/^lucy> /, "", line)
      if (seen_prompt==0) {
        seen_prompt=1
        if (length(line) > 0) {
          capturing=1
          print line
        }
        next
      }
      if (capturing) {
        if (length(line) > 0) print line
        exit
      }
      next
    }
    {
      if (seen_prompt==1) {
        capturing=1
        print
      }
    }
  ' | sed -E ':a;N;$!ba;s/\n+[[:space:]]*$/\n/; s/^[[:space:]]+//; s/[[:space:]]+$//'
}

FIRST_SENTENCE_EARLY_STARTED=0
FIRST_SENTENCE_TTS_PID=""
FIRST_SENTENCE_TTS_TEXT=""

prepare_first_sentence_tts_state(){
  FIRST_SENTENCE_EARLY_STARTED=0
  FIRST_SENTENCE_TTS_PID=""
  FIRST_SENTENCE_TTS_TEXT=""
}

abort_first_sentence_tts(){
  if [[ -n "${FIRST_SENTENCE_TTS_PID}" ]]; then
    kill -TERM "${FIRST_SENTENCE_TTS_PID}" >/dev/null 2>&1 || true
    wait "${FIRST_SENTENCE_TTS_PID}" >/dev/null 2>&1 || true
  fi
  prepare_first_sentence_tts_state
}

is_evidence_trigger_sentence(){
  local text="$1"
  local stripped
  stripped="$(printf '%s' "${text}" | sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//')"
  if printf '%s' "${stripped}" | grep -Eqi '^This requires evidence mode\.|^Run: run online:'; then
    return 0
  fi
  return 1
}

start_first_sentence_tts(){
  local sentence="$1"
  if [[ -z "${sentence//[[:space:]]}" ]] || [[ "${TTS_ENGINE}" == "none" ]]; then
    return 0
  fi
  FIRST_SENTENCE_TTS_TEXT="${sentence}"
  (
    speak_answer_once "${sentence}"
  ) &
  FIRST_SENTENCE_TTS_PID="$!"
  FIRST_SENTENCE_EARLY_STARTED=1
}

wait_for_first_sentence_tts(){
  local rc=1
  if [[ -n "${FIRST_SENTENCE_TTS_PID}" ]]; then
    set +e
    wait "${FIRST_SENTENCE_TTS_PID}" >/dev/null 2>&1
    rc=$?
    set -e
  fi
  prepare_first_sentence_tts_state
  return "${rc}"
}

maybe_start_first_sentence_tts(){
  local spoken="$1"
  local first
  first="$(split_tts_chunks "${spoken}" | head -n 1)"
  if [[ -z "${first//[[:space:]]}" ]]; then
    return 0
  fi
  if is_evidence_trigger_sentence "${first}"; then
    return 0
  fi
  start_first_sentence_tts "${first}"
}

run_chat_once(){
  local q="$1"
  local q_norm routed now_local
  q_norm="$(printf '%s' "${q}" | tr '[:upper:]' '[:lower:]' | sed -E 's/^[[:space:]]+|[[:space:]]+$//g; s/[[:space:]]+/ /g')"
  routed="${q}"

  is_local_time_date_query(){
    local t="$1"
    if printf '%s' "${t}" | grep -Eqi '(^|[^[:alnum:]_])(what time is it|time and date|date and time|today'"'"'?s date|today'"'"'?s time|current time|current date|time now|date today)([^[:alnum:]_]|$)'; then
      return 0
    fi
    return 1
  }

  if is_local_time_date_query "${q_norm}"; then
    now_local="$(date '+%A, %B %d, %Y %H:%M %Z (%z)')"
    printf '%s\n' "Local time and date: ${now_local}."
    return 0
  fi

  local route_ctl="AUTO"
  case "${VOICE_ROUTE_MODE}" in
    online) route_ctl="FORCED_ONLINE" ;;
    offline) route_ctl="FORCED_OFFLINE" ;;
    auto|*) route_ctl="AUTO" ;;
  esac

  if [[ "${VOICE_SESSION_MEMORY}" == "1" ]]; then
    printf '%s\n/exit\n' "${routed}" | LUCY_SURFACE="voice" LUCY_ROUTE_CONTROL_MODE="${route_ctl}" LUCY_CONVERSATION_MODE_FORCE="${VOICE_CONVERSATION_FORCE}" LUCY_ROUTER_PY="${LUCY_ROUTER_PY:-1}" LUCY_EXEC_PY="${LUCY_EXEC_PY:-1}" LUCY_NL_MEMORY_FILE="${VOICE_SESSION_MEMORY_FILE}" "${NL_CHAT_BIN}" 2>&1
  else
    printf '%s\n/exit\n' "${routed}" | LUCY_SURFACE="voice" LUCY_ROUTE_CONTROL_MODE="${route_ctl}" LUCY_CONVERSATION_MODE_FORCE="${VOICE_CONVERSATION_FORCE}" LUCY_ROUTER_PY="${LUCY_ROUTER_PY:-1}" LUCY_EXEC_PY="${LUCY_EXEC_PY:-1}" "${NL_CHAT_BIN}" 2>&1
  fi
}

voice_mode_allows_auto_evidence(){
  case "${VOICE_ROUTE_MODE}" in
    online|auto) return 0 ;;
  esac
  return 1
}

raw_output_requires_evidence_mode(){
  local raw="$1"
  printf '%s' "${raw}" | grep -Eqi '^This requires evidence mode\.|^Run: run online:'
}

run_chat_with_auto_evidence_escalation(){
  local q="$1" raw qn
  raw="$(run_chat_once "${q}")"
  if voice_mode_allows_auto_evidence && raw_output_requires_evidence_mode "${raw}"; then
    qn="$(printf '%s' "${q}" | tr '[:upper:]' '[:lower:]' | sed -E 's/^[[:space:]]+|[[:space:]]+$//g')"
    if [[ ! "${qn}" =~ ^(news:|evidence:)[[:space:]]* ]]; then
      raw="$(run_chat_once "evidence: ${q}")"
    fi
  fi
  printf '%s' "${raw}"
}

sanitize_tts_text(){
  local raw="$1"
  local cleaned=""
  local lowered=""

  cleaned="$(printf '%s\n' "${raw}" | sed -E 's/\x1B\[[0-9;]*[A-Za-z]//g' | awk '
    {
      line=$0
      is_list=0
      gsub(/\r/, "", line)
      sub(/^lucy>[[:space:]]*/, "", line)

      if (line ~ /^```/) next
      if (line ~ /^(Answer|Claims|Sources|Citations|Evidence|Confidence|Transcript|INFO|WARN|ERROR|DEBUG):/) next

      # Convert simple list markers to plain text.
      if (line ~ /^[[:space:]]*[-*][[:space:]]+/) {
        is_list=1
        sub(/^[[:space:]]*[-*][[:space:]]+/, "", line)
      } else if (line ~ /^[[:space:]]*[0-9]+\.[[:space:]]+/) {
        is_list=1
        sub(/^[[:space:]]*[0-9]+\.[[:space:]]+/, "", line)
      }
      sub(/[[:space:]]+$/, "", line)
      if (is_list) {
        if (line ~ /[.!?]["'"'"'”’)]*$/) {
          line = line ".."
        } else {
          line = line "..."
        }
      }

      print line
    }
  ' | sed -E \
      -e 's/\[([^][]+)\]\((https?:\/\/[^)]+)\)/\1/g' \
      -e 's/https?:\/\/[^[:space:]]+//g' \
      -e 's/`+//g' \
      -e 's/\*\*?//g' \
      -e 's/[[:space:]]+/ /g; s/^ +//; s/ +$//')"

  lowered="$(printf '%s' "${cleaned}" | tr '[:upper:]' '[:lower:]')"
  cleaned="$(printf '%s' "${cleaned}" | sed -E \
    -e 's/[Kk][Mm][[:space:]]*\/[[:space:]]*[Hh]/kilometers per hour/g' \
    -e 's/[Mm][Pp][Hh]/miles per hour/g' \
    -e 's/[[:space:]]+/ /g; s/^ +//; s/ +$//')"
  if printf '%s' "${lowered}" | grep -Eq '\b(recipe|ingredients?|instructions?|directions?|preheat|oven|bake|broil|roast|saute|simmer|stir|servings?|cups?|cup|tsp|teaspoons?|tbsp|tblsp|tablespoons?)\b'; then
    cleaned="$(printf '%s' "${cleaned}" | sed -E \
      -e 's/\b[Kk][Gg]\b/kilograms/g' \
      -e 's/\b[Ll][Bb]\b/pounds/g' \
      -e 's/\b[Tt][Bb][Ll][Ss][Pp]\b/tablespoon/g' \
      -e 's/\b[Tt][Ss][Pp]\b/teaspoons/g' \
      -e 's|/| or |g' \
      -e 's/[[:space:]]*-[[:space:]]*/ to /g' \
      -e 's/[[:space:]]+/ /g; s/^ +//; s/ +$//')"
  fi

  if [[ "${TTS_MAX_CHARS}" =~ ^[0-9]+$ ]] && [[ "${TTS_MAX_CHARS}" -gt 0 ]] && [[ "${#cleaned}" -gt "${TTS_MAX_CHARS}" ]]; then
    cleaned="${cleaned:0:${TTS_MAX_CHARS}}"
  fi

  printf '%s' "${cleaned}"
}

split_tts_chunks(){
  local text="$1"
  printf '%s' "${text}" \
    | tr '\n\r' ' ' \
    | sed -E 's/[[:space:]]+/ /g; s/^ +//; s/ +$//' \
    | sed -E 's/([.!?;:])[[:space:]]+/\1\n/g' \
    | awk '
      {
        gsub(/^[[:space:]]+|[[:space:]]+$/, "", $0)
        if (length($0)==0) next
        print
      }
    '
}

tts_json_field(){
  local payload="$1"
  local key="$2"
  PAYLOAD="${payload}" "${VOICE_PYTHON_BIN}" - "${key}" <<'PY'
import json
import os
import sys

key = sys.argv[1]
raw = os.environ.get("PAYLOAD", "").strip()
if not raw:
    raise SystemExit(1)
try:
    payload = json.loads(raw)
except json.JSONDecodeError:
    raise SystemExit(1)
value = payload.get(key, "")
if isinstance(value, bool):
    print("true" if value else "false")
elif value is None:
    print("")
else:
    print(value)
PY
}

speak_answer_once(){
  local text="$1"
  local prepad_override_ms="${2:-}"
  local prime_override_ms="${3:-}"
  local payload ok wav_path actual_engine prepad_ms
  [[ -n "${text// }" ]] || return 0

  [[ "${TTS_ENGINE}" != "none" ]] || return 0
  [[ -f "${TTS_ADAPTER}" && -f "${TTS_PLAYBACK}" ]] || return 1

  if [[ "${TTS_ENGINE}" == "kokoro" ]] && [[ -n "${KOKORO_WORKER_PID}" ]]; then
    payload="$(kokoro_worker_synthesize "${text}" || true)"
  else
    payload="$("${VOICE_PYTHON_BIN}" "${TTS_ADAPTER}" synthesize --engine "${TTS_ENGINE_REQ}" --output-dir "${RUN_DIR}" --text "${text}" 2>/dev/null || true)"
  fi
  ok="$(tts_json_field "${payload}" ok || true)"
  [[ "${ok}" == "true" ]] || return 1

  wav_path="$(tts_json_field "${payload}" wav_path || true)"
  actual_engine="$(tts_json_field "${payload}" engine || true)"
  [[ -n "${wav_path}" && -s "${wav_path}" ]] || return 1

  prepad_ms=0
  if [[ "${prepad_override_ms}" =~ ^[0-9]+$ ]]; then
    prepad_ms="${prepad_override_ms}"
  elif [[ "${actual_engine}" == "piper" ]] && [[ "${PIPER_PREPAD_MS}" =~ ^[0-9]+$ ]]; then
    prepad_ms="${PIPER_PREPAD_MS}"
  elif [[ "${actual_engine}" == "kokoro" ]] && [[ "${KOKORO_PREPAD_MS}" =~ ^[0-9]+$ ]]; then
    prepad_ms="${KOKORO_PREPAD_MS}"
  fi

  if ! "${VOICE_PYTHON_BIN}" "${TTS_PLAYBACK}" --wav "${wav_path}" --prepad-ms "${prepad_ms}" --prime-ms "${prime_override_ms}" >/dev/null 2>&1; then
    rm -f "${wav_path}" >/dev/null 2>&1 || true
    return 1
  fi
  rm -f "${wav_path}" >/dev/null 2>&1 || true
  return 0
}

speak_answer(){
  local text="$1"
  local skip_first_chunk=0
  local chunk_index=0
  local chunk=""
  local spoke_any=0
  local rc=0
  local pause_ms=56
  local chunk_prepad_ms=0
  local chunk_prime_ms=0

  [[ -n "${text// }" ]] || return 0

  if [[ "${TTS_CHUNK_PAUSE_MS}" =~ ^[0-9]+$ ]]; then
    pause_ms="${TTS_CHUNK_PAUSE_MS}"
  fi

  if [[ "${FIRST_SENTENCE_EARLY_STARTED}" == "1" ]]; then
    if wait_for_first_sentence_tts; then
      skip_first_chunk=1
    fi
  fi

  while IFS= read -r chunk; do
    [[ -n "${chunk// }" ]] || continue
    if (( skip_first_chunk && chunk_index == 0 )); then
      chunk_index=$((chunk_index + 1))
      continue
    fi
    spoke_any=1
    chunk_prepad_ms=0
    chunk_prime_ms=0
    if (( chunk_index == 0 )) && [[ "${TTS_ENGINE}" == "kokoro" ]] && [[ "${KOKORO_FIRST_CHUNK_PREPAD_MS}" =~ ^[0-9]+$ ]]; then
      chunk_prepad_ms="${KOKORO_FIRST_CHUNK_PREPAD_MS}"
    fi
    if (( chunk_index == 0 )) && [[ "${TTS_ENGINE}" == "kokoro" ]] && [[ "${KOKORO_FIRST_CHUNK_PLAYER_PRIME_MS}" =~ ^[0-9]+$ ]]; then
      chunk_prime_ms="${KOKORO_FIRST_CHUNK_PLAYER_PRIME_MS}"
    fi
    if ! speak_answer_once "${chunk}" "${chunk_prepad_ms}" "${chunk_prime_ms}"; then
      rc=1
      break
    fi
    if (( pause_ms > 0 )); then
      sleep "$(awk "BEGIN { printf \"%.3f\", ${pause_ms}/1000 }")"
    fi
    chunk_index=$((chunk_index + 1))
  done < <(split_tts_chunks "${text}")

  if (( spoke_any == 0 )); then
    if (( skip_first_chunk == 1 )); then
      return 0
    fi
    chunk_prepad_ms=0
    chunk_prime_ms=0
    if [[ "${TTS_ENGINE}" == "kokoro" ]] && [[ "${KOKORO_FIRST_CHUNK_PREPAD_MS}" =~ ^[0-9]+$ ]]; then
      chunk_prepad_ms="${KOKORO_FIRST_CHUNK_PREPAD_MS}"
    fi
    if [[ "${TTS_ENGINE}" == "kokoro" ]] && [[ "${KOKORO_FIRST_CHUNK_PLAYER_PRIME_MS}" =~ ^[0-9]+$ ]]; then
      chunk_prime_ms="${KOKORO_FIRST_CHUNK_PLAYER_PRIME_MS}"
    fi
    speak_answer_once "${text}" "${chunk_prepad_ms}" "${chunk_prime_ms}" || rc=1
  fi

  return "${rc}"
}

pick_recorder
pick_stt
pick_tts
start_kokoro_worker
init_keyboard_input

echo "=== Local Lucy Voice PTT v1 ==="
echo "Recorder: ${REC_ENGINE}"
echo "STT: ${STT_ENGINE}"
echo "TTS: ${TTS_ENGINE}"
echo "Piper voice: ${VOICE_PIPER_VOICE}"
echo "PTT mode: ${PTT_MODE}"
echo "Conversation mode: $([[ "${VOICE_CONVERSATION_FORCE}" == "1" ]] && echo on || echo off)"
if [[ "${VOICE_SESSION_MEMORY}" == "1" ]]; then
  echo "Voice memory: ON (say '/memory status' or '/memory clear')"
else
  echo "Voice memory: OFF (set LUCY_VOICE_SESSION_MEMORY=1 to enable)"
fi
echo

while true; do
  abort_first_sentence_tts
  case "${PTT_MODE}" in
    hold)
      printf '[hold Space to record, release to stop | press q to exit voice] '
      record_wav_hold_space
      rc=$?
      if [[ "${rc}" == "2" ]]; then
        echo
        echo "Exiting voice mode."
        exit 0
      fi
      if [[ "${rc}" != "0" ]]; then
        echo
        echo "ERROR: recording failed"
        log_event "" "record_error"
        if [[ "${ONESHOT}" == "1" ]]; then
          exit 1
        fi
        continue
      fi
      echo
      ;;
    enter|*)
      if [[ "${ONESHOT}" == "1" ]]; then
        printf '[press enter to record once | type q then enter to cancel] '
      else
        printf '[press enter to record | type q then enter to exit voice] '
      fi
      if ! IFS= read -r -u "${KEYBOARD_FD}" cmd; then
        echo
        exit 0
      fi
      cmd_norm="$(printf '%s' "${cmd}" | tr '[:upper:]' '[:lower:]' | sed -E 's/^[[:space:]]+|[[:space:]]+$//g')"
      case "${cmd_norm}" in
        q|quit|/quit|/exit|/back)
          echo "Exiting voice mode."
          exit 0
          ;;
      esac
      if ! record_wav; then
        echo "ERROR: recording failed"
        log_event "" "record_error"
        continue
      fi
      ;;
  esac

  transcript="$(transcribe "${VOICE_WAV}")"
  if [[ -n "${STT_LAST_ERROR}" ]]; then
    echo "ERROR: ${STT_LAST_ERROR}"
    log_event "" "stt_error"
    rm -f "${VOICE_WAV}" >/dev/null 2>&1 || true
    if [[ "${ONESHOT}" == "1" ]]; then
      exit_oneshot 1
    fi
    continue
  fi
  transcript="$(normalize_transcript "${transcript}")"
  transcript="$(trim_transcript_hallucinated_prefix "${transcript}")"
  transcript="$(map_spoken_command "${transcript}")"
  if is_blank_transcript "${transcript}"; then
    echo "Transcript:"
    echo "Answer:"
    echo "(no transcript)"
    log_event "" "empty_transcript"
    rm -f "${VOICE_WAV}" >/dev/null 2>&1 || true
    if [[ "${ONESHOT}" == "1" ]]; then
      exit_oneshot 0
    fi
    continue
  fi

  transcript="$(printf '%s' "${transcript}" | sed -E 's/[[:space:]]+/ /g; s/^ +//; s/ +$//')"
  echo "Transcript: ${transcript}"

  cmd_rc=1
  set +e
  handle_voice_session_command "${transcript}"
  cmd_rc=$?
  set -e
  if [[ "${cmd_rc}" == "10" ]]; then
    log_event "${transcript}" "voice_exit_command"
    echo "Exiting voice mode."
    exit 0
  fi
  if [[ "${cmd_rc}" == "0" ]]; then
    log_event "${transcript}" "voice_command"
    rm -f "${VOICE_WAV}" >/dev/null 2>&1 || true
    if [[ "${ONESHOT}" == "1" ]]; then
      exit_oneshot 0
    fi
    echo
    continue
  fi

  transcript_query="$(rewrite_implicit_pet_feed_query "${transcript}")"
  chat_raw="$(run_chat_with_auto_evidence_escalation "${transcript_query}")"
  answer_block="$(extract_answer_block "${chat_raw}")"
  if [[ -z "${answer_block// }" ]]; then
    answer_block="$(extract_first_nl_answer "${chat_raw}")"
  fi
  if [[ -z "${answer_block// }" ]]; then
    answer_block="$(printf '%s\n' "${chat_raw}" | sed -E 's/^lucy> //')"
  fi
  answer_block="$(shape_voice_answer_block "${answer_block}")"

  spoken_text="${answer_block}"
  if [[ "${TTS_CLEAN}" == "1" ]]; then
    spoken_text="$(sanitize_tts_text "${answer_block}")"
    if [[ -z "${spoken_text// }" ]]; then
      spoken_text="${answer_block}"
    fi
  fi
  maybe_start_first_sentence_tts "${spoken_text}"

  echo "Answer:"
  printf '%s\n' "${answer_block}"

  speak_status="ok"
  if ! speak_answer "${spoken_text}"; then
    speak_status="tts_error"
  fi

  log_event "${transcript}" "${speak_status}"

  rm -f "${VOICE_WAV}" >/dev/null 2>&1 || true

  if [[ "${ONESHOT}" == "1" ]]; then
    exit_oneshot 0
  fi

  echo

done
