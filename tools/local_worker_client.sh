#!/usr/bin/env bash

local_worker_client_b64_encode(){
  if base64 --help 2>&1 | grep -q -- ' -w'; then
    base64 -w 0
    return
  fi
  base64 | tr -d '\n'
}

local_worker_client_transport(){
  printf '%s' "${LUCY_LOCAL_WORKER_TRANSPORT:-unix}"
}

local_worker_client_tool(){
  printf '%s' "${LUCY_LOCAL_WORKER_TOOL:-${ROOT}/tools/local_worker.py}"
}

local_worker_client_request_fifo(){
  printf '%s' "${LUCY_LOCAL_WORKER_REQUEST_FIFO:-${ROOT}/tmp/run/local_worker.request.fifo}"
}

local_worker_client_pid_file(){
  printf '%s' "${LUCY_LOCAL_WORKER_PID_FILE:-${ROOT}/tmp/run/local_worker.pid}"
}

local_worker_client_code_stamp_file(){
  printf '%s' "${LUCY_LOCAL_WORKER_CODE_STAMP_FILE:-${ROOT}/tmp/run/local_worker.code_stamp}"
}

local_worker_client_expected_code_stamp(){
  local answer_path worker_path
  answer_path="${ROOT}/tools/local_answer.sh"
  worker_path="${ROOT}/tools/local_worker.py"
  [[ -f "${answer_path}" && -f "${worker_path}" ]] || return 1
  python3 - "$answer_path" "$worker_path" <<'PY'
import os, sys
parts = []
for path in sys.argv[1:]:
    st = os.stat(path)
    parts.append(f"{path}:{int(st.st_mtime_ns)}:{int(st.st_size)}")
print("|".join(parts))
PY
}

local_worker_client_enabled(){
  case "$(printf '%s' "${LUCY_LOCAL_WORKER_ENABLED:-1}" | tr '[:upper:]' '[:lower:]')" in
    1|true|yes|on) ;;
    *) return 1 ;;
  esac
  [[ -f "$(local_worker_client_tool)" ]] || return 1
  command -v python3 >/dev/null 2>&1 || return 1
  return 0
}

local_worker_client_running(){
  local pid_file pid expected_stamp current_stamp
  pid_file="$(local_worker_client_pid_file)"
  [[ -f "${pid_file}" ]] || return 1
  pid="$(tr -d '[:space:]' < "${pid_file}" 2>/dev/null || true)"
  [[ "${pid}" =~ ^[0-9]+$ ]] || return 1
  kill -0 "${pid}" 2>/dev/null || return 1
  expected_stamp="$(local_worker_client_expected_code_stamp 2>/dev/null || true)"
  [[ -n "${expected_stamp}" ]] || return 1
  [[ -f "$(local_worker_client_code_stamp_file)" ]] || return 1
  current_stamp="$(tr -d '[:space:]' < "$(local_worker_client_code_stamp_file)" 2>/dev/null || true)"
  [[ "${current_stamp}" == "${expected_stamp}" ]]
}

local_worker_client_ensure(){
  local tool transport
  tool="$(local_worker_client_tool)"
  transport="$(local_worker_client_transport)"
  [[ -f "${tool}" ]] || return 1
  LUCY_LOCAL_WORKER_TRANSPORT="${transport}" python3 "${tool}" ensure >/dev/null 2>&1
}

local_worker_client_build_env_shell(){
  local key value keys="" script="" quoted_keys
  for key in \
    LUCY_ROOT \
    LUCY_LOCAL_MODEL \
    LUCY_OLLAMA_API_URL \
    LUCY_LOCAL_TEMPERATURE \
    LUCY_LOCAL_TOP_P \
    LUCY_LOCAL_SEED \
    LUCY_LOCAL_KEEP_ALIVE \
    LUCY_SESSION_MEMORY_CONTEXT \
    LUCY_CONVERSATION_MODE_ACTIVE \
    LUCY_CONVERSATION_MODE_FORCE \
    LUCY_CONVERSATION_SYSTEM_BLOCK \
    LUCY_IDENTITY_TRACE_FILE \
    LUCY_LOCAL_POLICY_RESPONSE_ID \
    LUCY_LOCAL_REPEAT_CACHE \
    LUCY_LOCAL_REPEAT_CACHE_DIR \
    LUCY_LOCAL_REPEAT_CACHE_TTL_S \
    LUCY_LOCAL_REPEAT_CACHE_MAX_ENTRIES \
    LUCY_LOCAL_PROMPT_GUARD_TOKENS \
    LUCY_LOCAL_GEN_ROUTE_MODE \
    LUCY_LOCAL_GEN_OUTPUT_MODE \
    LUCY_LOCAL_NUM_PREDICT_DEFAULT \
    LUCY_LOCAL_NUM_PREDICT_CHAT \
    LUCY_LOCAL_NUM_PREDICT_CONVERSATION \
    LUCY_LOCAL_NUM_PREDICT_BRIEF \
    LUCY_LOCAL_NUM_PREDICT_DETAIL \
    LUCY_LOCAL_NUM_PREDICT_CLARIFY \
    LUCY_LOCAL_DIAG_FILE \
    LUCY_LOCAL_DIAG_RUN_ID \
    LUCY_LATENCY_PROFILE_ACTIVE \
    LUCY_LATENCY_PROFILE_FILE \
    LUCY_LATENCY_RUN_ID \
    LUCY_LOCAL_MODEL_PRELOADED \
    LUCY_TOOLS_DIR
  do
    value="${!key-}"
    [[ -n "${value}" ]] || continue
    if [[ -z "${keys}" ]]; then
      keys="${key}"
    else
      keys="${keys} ${key}"
    fi
    script+="export ${key}="
    printf -v quoted_keys '%q' "${value}"
    script+="${quoted_keys}"$'\n'
  done
  [[ -n "${keys}" ]] || return 0
  printf -v quoted_keys '%q' "${keys}"
  printf 'LOCAL_ANSWER_WORKER_ENV_KEYS=%s\n%s' "${quoted_keys}" "${script}"
}

local_worker_client_request_fifo_call(){
  local q="$1" fifo response_path response_raw out rc line encoded env_shell serialize_started_ms
  fifo="$(local_worker_client_request_fifo)"
  mkdir -p "$(dirname "${fifo}")"
  [[ -p "${fifo}" ]] || return 1
  # FIX: Use mktemp for secure temp file creation instead of predictable $$.$RANDOM.
  # Creates temp file in standard tmpdir with proper permissions, then uses that
  # as the base name for the FIFO in the target directory.
  local _tmp_response_base
  _tmp_response_base="$(mktemp -u "${TMPDIR:-/tmp}/lucy_response.XXXXXX.$$")"
  response_path="${ROOT}/tmp/run/$(basename "${_tmp_response_base}").fifo"
  rm -f "${response_path}"
  mkfifo -m 600 "${response_path}" || return 1
  serialize_started_ms="$(date +%s%3N)"
  env_shell="$(local_worker_client_build_env_shell || true)"
  latprof_append "local_worker" "request_serialize" "$(( $(date +%s%3N) - serialize_started_ms ))"
  {
    printf 'BEGIN_REQUEST\n'
    printf 'RESPONSE\t%s\n' "${response_path}"
    printf 'COMMAND\trequest\n'
    printf 'QUESTION\t%s\n' "$(printf '%s' "${q}" | local_worker_client_b64_encode)"
    if [[ -n "${env_shell}" ]]; then
      printf 'ENV_SHELL\t%s\n' "$(printf '%s' "${env_shell}" | local_worker_client_b64_encode)"
    fi
    printf 'END_REQUEST\n'
  } > "${fifo}"

  response_raw="$(timeout 180s cat "${response_path}" 2>/dev/null || true)"
  rm -f "${response_path}"
  [[ -n "${response_raw}" ]] || return 1

  rc=1
  out=""
  while IFS= read -r line; do
    case "${line}" in
      RC$'\t'*) rc="${line#RC$'\t'}" ;;
      OUTPUT$'\t'*)
        encoded="${line#OUTPUT$'\t'}"
        out="$(printf '%s' "${encoded}" | base64 -d 2>/dev/null || true)"
        ;;
    esac
  done <<< "${response_raw}"
  printf '%s' "${out}"
  return "${rc}"
}

local_worker_client_request(){
  local q="$1" tool transport started_ms setup_started_ms
  tool="$(local_worker_client_tool)"
  transport="$(local_worker_client_transport)"
  setup_started_ms="$(date +%s%3N)"
  if [[ "${transport}" == "fifo" ]]; then
    if ! local_worker_client_running || [[ ! -p "$(local_worker_client_request_fifo)" ]]; then
      local_worker_client_ensure || return 1
    fi
    latprof_append "local_worker" "request_setup" "$(( $(date +%s%3N) - setup_started_ms ))"
    started_ms="$(date +%s%3N)"
    if local_worker_client_request_fifo_call "${q}"; then
      latprof_append "local_worker" "request_roundtrip" "$(( $(date +%s%3N) - started_ms ))"
      latprof_append "local_worker" "client_roundtrip" "$(( $(date +%s%3N) - started_ms ))"
      return 0
    fi
    local_worker_client_ensure || return 1
    if local_worker_client_request_fifo_call "${q}"; then
      latprof_append "local_worker" "request_roundtrip" "$(( $(date +%s%3N) - started_ms ))"
      latprof_append "local_worker" "client_roundtrip" "$(( $(date +%s%3N) - started_ms ))"
      return 0
    fi
    return 1
  fi
  latprof_append "local_worker" "request_setup" "$(( $(date +%s%3N) - setup_started_ms ))"
  started_ms="$(date +%s%3N)"
  if LUCY_LOCAL_WORKER_TRANSPORT="${transport}" python3 "${tool}" request --question "${q}"; then
    latprof_append "local_worker" "request_roundtrip" "$(( $(date +%s%3N) - started_ms ))"
    latprof_append "local_worker" "client_roundtrip" "$(( $(date +%s%3N) - started_ms ))"
    return 0
  fi
  return 1
}
