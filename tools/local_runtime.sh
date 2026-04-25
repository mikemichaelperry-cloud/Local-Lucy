#!/usr/bin/env bash

local_truthy() {
  case "$(printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]')" in
    1|true|yes|on) return 0 ;;
  esac
  return 1
}

local_estimate_tokens_text() {
  local txt="${1:-}" chars
  chars="${#txt}"
  if [[ "${chars}" -le 0 ]]; then
    printf '0'
    return 0
  fi
  printf '%s' "$(( (chars + 3) / 4 ))"
}

local_diag_append() {
  local metric="${1:-}" value="${2:-}"
  local diag_file="${LUCY_LOCAL_DIAG_FILE:-}" run_id="${LUCY_LOCAL_DIAG_RUN_ID:-}"
  [[ -n "${diag_file}" ]] || return 0
  [[ -n "${run_id}" ]] || return 0
  mkdir -p "$(dirname -- "${diag_file}")"
  printf 'run=%s\tmetric=%s\tvalue=%s\n' "${run_id}" "${metric}" "${value}" >> "${diag_file}"
}

local_ollama_model_loaded() {
  local model="${1:-}"
  [[ -n "${model}" ]] || return 1
  command -v ollama >/dev/null 2>&1 || return 1
  ollama ps 2>/dev/null | awk -v want="${model}" '
    NR > 1 {
      raw=$1
      base=raw
      sub(/:.*/, "", base)
      if (raw == want || base == want) {
        found=1
      }
    }
    END { exit(found ? 0 : 1) }
  '
}

local_model_loaded_hint() {
  local model="${1:-}" hint="${LUCY_LOCAL_MODEL_PRELOADED:-}"
  if [[ -n "${hint}" ]]; then
    if local_truthy "${hint}"; then
      printf '1'
    else
      printf '0'
    fi
    return 0
  fi
  if local_ollama_model_loaded "${model}"; then
    printf '1'
  else
    printf '0'
  fi
}

local_ensure_model_loaded() {
  local model="${1:-}" api_url="${2:-http://127.0.0.1:11434/api/generate}" keep_alive="${3:-10m}"
  [[ -n "${model}" ]] || return 1
  if local_ollama_model_loaded "${model}"; then
    return 0
  fi

  if command -v curl >/dev/null 2>&1; then
    curl -fsS --max-time 60 \
      -H 'Content-Type: application/json' \
      -d "{\"model\":\"${model}\",\"prompt\":\"\",\"stream\":false,\"keep_alive\":\"${keep_alive}\",\"options\":{\"num_predict\":0}}" \
      "${api_url}" >/dev/null 2>&1 || true
  fi

  if local_ollama_model_loaded "${model}"; then
    return 0
  fi

  ollama run "${model}" "" >/dev/null 2>&1 || true
  local_ollama_model_loaded "${model}"
}
