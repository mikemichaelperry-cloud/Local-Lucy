#!/usr/bin/env bash
# ROLE: SUPPORTED ALIAS / WRAPPER
# Interactive natural-language shell over the active backend executable.
# Supported terminal convenience surface; not the primary launcher.
set -euo pipefail
umask 077

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${LUCY_ROOT:-$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)}"
CHAT="${LUCY_CHAT_BIN:-${ROOT}/lucy_chat.sh}"
STACK_CHECK="${ROOT}/tools/internet/ensure_stack.sh"
INCIDENT_TOOL="${LUCY_INCIDENT_TOOL:-${ROOT}/tools/internet/collect_docker_incident.sh}"
HEALTH_TOOL="${LUCY_HEALTH_TOOL:-${ROOT}/tools/internet/internet_health.sh}"
INCIDENT_TIMEOUT_S="${LUCY_INCIDENT_TIMEOUT_S:-25}"
VOICE_TOOL="${LUCY_VOICE_TOOL:-${ROOT}/tools/lucy_voice_ptt.sh}"

MEM_ENABLED="${LUCY_MEM_ENABLED:-1}"
MEM_MAX_TURNS="${LUCY_MEM_MAX_TURNS:-4}"
if ! [[ "${MEM_MAX_TURNS}" =~ ^[0-9]+$ ]] || [[ "${MEM_MAX_TURNS}" -lt 1 ]]; then
  MEM_MAX_TURNS=4
fi
if [[ "${MEM_ENABLED}" != "0" && "${MEM_ENABLED}" != "1" ]]; then
  MEM_ENABLED=1
fi
if ! [[ "${INCIDENT_TIMEOUT_S}" =~ ^[0-9]+$ ]] || [[ "${INCIDENT_TIMEOUT_S}" -lt 1 ]]; then
  INCIDENT_TIMEOUT_S=25
fi
declare -a MEM_USER=()
declare -a MEM_ASSIST=()
PENDING_FOLLOWUP_QUERY=""
MEM_FILE_OVERRIDE="${LUCY_NL_MEMORY_FILE:-}"
MEM_FILE=""
MEM_FILE_OWNED=1
if [[ -n "${MEM_FILE_OVERRIDE}" ]]; then
  MEM_FILE="${MEM_FILE_OVERRIDE}"
  mkdir -p "$(dirname -- "${MEM_FILE}")"
  touch "${MEM_FILE}"
  MEM_FILE_OWNED=0
else
  MEM_FILE="$(mktemp)"
fi
if [[ "${MEM_FILE_OWNED}" == "1" ]]; then
  trap 'rm -f "${MEM_FILE}"' EXIT
fi

[[ -x "${CHAT}" ]] || { echo "ERR: missing executable: ${CHAT}" >&2; exit 2; }

echo "=== Local Lucy (Locked NL Chat) ==="
echo "Type natural language questions. Use /exit to quit."
echo "Memory commands: /memory on|off|show|clear"
echo "Diagnostics: /incident"
echo "Health: /health"
echo "Voice: /voice"
if [[ -x "${STACK_CHECK}" ]]; then
  "${STACK_CHECK}" >/dev/null 2>&1 || true
fi
echo

render_clean(){
  printf '%s\n' "$1" \
    | sed '/^BEGIN_VALIDATED$/d; /^END_VALIDATED$/d' \
    | sed -E $'s/\x1B\\[[0-9;?]*[ -/]*[@-~]//g' \
    | sed -E $'s/\x1B\\][^\x07]*(\x07|\x1B\\\\)//g' \
    | sed -E 's/\[(1G|2K|K)//g' \
    | tr -d '\000-\010\013\014\016-\037\177' \
    | perl -CSDA -pe 's/[\x{2800}-\x{28FF}]//g' \
    | sed -E 's/\[\?[0-9;]+[A-Za-z]//g'
}

memory_unsafe_query(){
  local qpol
  qpol="${ROOT}/tools/query_policy.sh"
  if [[ -x "${qpol}" ]]; then
    if "${qpol}" is-memory-unsafe "$1" >/dev/null 2>&1; then
      return 0
    fi
    return 1
  fi
  local q_norm
  q_norm="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | sed -E 's/^[[:space:]]+|[[:space:]]+$//g; s/[[:space:]]+/ /g')"
  # Avoid memory contamination on news/evidence/time-sensitive turns.
  if printf '%s' "${q_norm}" | grep -Eqi '(^|[^[:alnum:]_])(news|headline|headlines|breaking|latest|recent|today|current|update|updates|source|sources|citation|citations|evidence|verify|wikipedia|wiki|fetch|browse|search web|website|url|http)([^[:alnum:]_]|$)'; then
    return 0
  fi
  if printf '%s' "${q_norm}" | grep -Eqi '(^|[^[:alnum:]_])(price|stock|quote|market|inflation|exchange rate|currency|fx|weather|temperature|schedule)([^[:alnum:]_]|$)'; then
    return 0
  fi
  if printf '%s' "${q_norm}" | grep -Eqi '(^|[^[:alnum:]_])(tadalafil|tadalifil|cialis|viagra|sildenafil|vardenafil|metformin|statin|insulin|dose|dosage|side effect|interaction|interactions|contraindication|contraindications|medication|drug|drugs|alcohol)([^[:alnum:]_]|$)|react[[:space:]]+with'; then
    return 0
  fi
  return 1
}

refresh_memory_file(){
  : > "${MEM_FILE}"
  local i
  for ((i=0; i<${#MEM_USER[@]}; i++)); do
    printf 'User: %s\n' "${MEM_USER[$i]}" >> "${MEM_FILE}"
    printf 'Assistant: %s\n\n' "${MEM_ASSIST[$i]}" >> "${MEM_FILE}"
  done
}

load_memory_file(){
  [[ -s "${MEM_FILE}" ]] || return 0
  local cur_u=""
  local line=""
  while IFS= read -r line; do
    case "${line}" in
      "User: "*)
        cur_u="${line#User: }"
        ;;
      "Assistant: "*)
        if [[ -n "${cur_u}" ]]; then
          MEM_USER+=("${cur_u}")
          MEM_ASSIST+=("${line#Assistant: }")
        fi
        cur_u=""
        ;;
    esac
  done < "${MEM_FILE}"
  memory_trim
  refresh_memory_file
}

memory_trim(){
  while (( ${#MEM_USER[@]} > MEM_MAX_TURNS )); do
    MEM_USER=("${MEM_USER[@]:1}")
  done
  while (( ${#MEM_ASSIST[@]} > MEM_MAX_TURNS )); do
    MEM_ASSIST=("${MEM_ASSIST[@]:1}")
  done
}

memory_add_turn(){
  local u="$1"
  local a="$2"
  MEM_USER+=("$u")
  MEM_ASSIST+=("$(printf '%s' "$a" | tr '\n' ' ' | sed -E 's/ +/ /g; s/^ +//; s/ +$//')")
  memory_trim
  refresh_memory_file
}

memory_status(){
  local state="off"
  [[ "${MEM_ENABLED}" == "1" ]] && state="on"
  echo "Memory: ${state} turns=${#MEM_USER[@]}/${MEM_MAX_TURNS}"
}

is_affirmative_followup(){
  local q
  q="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | sed -E "s/[[:punct:]]+/ /g; s/[[:space:]]+/ /g; s/^ +| +$//g")"
  case "${q}" in
    yes|yep|yeah|yup|yes\ please|yes\ plz|please|sure|ok|okay|affirmative)
      return 0
      ;;
  esac
  return 1
}

pending_followup_from_answer(){
  local a n
  a="$1"
  n="$(printf '%s' "${a}" | tr '[:upper:]' '[:lower:]' | sed -E 's/[[:space:]]+/ /g; s/^ +| +$//g')"
  # Narrow deterministic bridge for voice clarification:
  # "Do you want Israel local delivery?" + "Yes, please." -> "latest Israel news"
  if printf '%s' "${n}" | grep -Eq '(^|[^[:alnum:]_])do you want israel local delivery\?'; then
    printf '%s\n' 'latest Israel news'
    return 0
  fi
  return 1
}

load_memory_file

while true; do
  printf "lucy> "
  if ! IFS= read -r line; then
    echo
    exit 0
  fi

  case "${line}" in
    /exit|/quit) exit 0 ;;
    /memory\ on)
      MEM_ENABLED=1
      memory_status
      echo
      continue
      ;;
    /memory\ off)
      MEM_ENABLED=0
      memory_status
      echo
      continue
      ;;
    /memory\ clear)
      MEM_USER=()
      MEM_ASSIST=()
      : > "${MEM_FILE}"
      memory_status
      echo
      continue
      ;;
    /memory\ show)
      memory_status
      if (( ${#MEM_USER[@]} == 0 )); then
        echo "(empty)"
      else
        cat "${MEM_FILE}"
      fi
      echo
      continue
      ;;
    /incident)
      if [[ -x "${INCIDENT_TOOL}" ]]; then
        rc_i=0
        out_i="$(timeout "${INCIDENT_TIMEOUT_S}s" "${INCIDENT_TOOL}" 2>&1)" || rc_i=$?
        if [[ "${rc_i}" == "124" || "${rc_i}" == "137" ]]; then
          printf 'WARN: incident collection timed out after %ss\n\n' "${INCIDENT_TIMEOUT_S}"
        elif [[ "${rc_i}" -ne 0 ]]; then
          printf 'WARN: incident collection failed (rc=%s)\n' "${rc_i}"
          printf '%s\n\n' "${out_i}"
        else
          printf '%s\n\n' "${out_i}"
        fi
      else
        echo "ERR: incident tool missing: ${INCIDENT_TOOL}"
        echo
      fi
      continue
      ;;
    /health)
      if [[ -x "${HEALTH_TOOL}" ]]; then
        out_h="$("${HEALTH_TOOL}" --live 2>&1 || true)"
        printf '%s\n\n' "${out_h}"
      else
        echo "ERR: health tool missing: ${HEALTH_TOOL}"
        echo
      fi
      continue
      ;;
    /voice)
      if [[ -x "${VOICE_TOOL}" ]]; then
        echo "Launching voice mode (Space hold-to-talk). Press Ctrl+C to return."
        echo
        LUCY_VOICE_PTT_MODE=hold "${VOICE_TOOL}" || true
        echo
      else
        echo "ERR: voice tool missing: ${VOICE_TOOL}"
        echo
      fi
      continue
      ;;
  esac

  [[ -n "${line// }" ]] || continue

  if [[ -n "${PENDING_FOLLOWUP_QUERY}" ]] && is_affirmative_followup "${line}"; then
    line="${PENDING_FOLLOWUP_QUERY}"
  fi

  skip_mem_turn=0
  if [[ "${MEM_ENABLED}" == "1" ]] && memory_unsafe_query "${line}"; then
    skip_mem_turn=1
  fi

  if [[ "${MEM_ENABLED}" == "1" && "${skip_mem_turn}" == "0" ]]; then
    out="$(LUCY_SURFACE="conversation" LUCY_CHAT_MEMORY_FILE="${MEM_FILE}" "${CHAT}" "${line}" 2>&1 || true)"
  else
    out="$(LUCY_SURFACE="conversation" "${CHAT}" "${line}" 2>&1 || true)"
  fi
  clean="$(render_clean "${out}")"
  printf '%s\n' "${clean}"
  PENDING_FOLLOWUP_QUERY="$(pending_followup_from_answer "${clean}" || true)"
  if [[ "${MEM_ENABLED}" == "1" && "${skip_mem_turn}" == "0" ]]; then
    memory_add_turn "${line}" "${clean}"
  fi
  echo
done
