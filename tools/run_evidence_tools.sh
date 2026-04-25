#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${LUCY_ROOT:-$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)}"
TOOLS_DIR="${LUCY_TOOLS_DIR:-${ROOT}/tools}"
EVID_ONLY="${TOOLS_DIR}/run_evidence_only.sh"

err(){ echo "ERR: $*" >&2; }

trim(){
  local s="$1"
  s="${s#"${s%%[!$' \t\r\n']*}"}"
  s="${s%"${s##*[!$' \t\r\n']}"}"
  printf '%s' "$s"
}

is_safe_lucy_path(){
  local p="$1"
  [[ -n "${p}" ]] || return 1
  [[ "${p}" == "${ROOT}/"* ]] || return 1
  [[ -f "${p}" ]] || return 1
  [[ ! -L "${p}" ]] || return 1
  return 0
}

run_tool(){
  local q="$1"
  local spec tool rest path

  spec="${q#tool:}"
  spec="$(trim "${spec}")"
  tool="${spec%%[[:space:]]*}"
  rest="${spec#${tool}}"
  rest="$(trim "${rest}")"

  case "${tool}" in
    sha256)
      printf '%s' "${rest}" | sha256sum | awk '{print $1}'
      ;;
    readfile)
      path="${rest}"
      is_safe_lucy_path "${path}" || { err "readfile path rejected: ${path}"; exit 34; }
      [[ -r "${path}" ]] || { err "readfile not readable: ${path}"; exit 35; }
      cat "${path}"
      ;;
    *)
      err "unsupported tool: ${tool}"
      exit 2
      ;;
  esac
}

main(){
  local q="${*:-}"
  q="$(trim "${q}")"
  [[ -n "${q}" ]] || { err "empty input"; exit 2; }

  if printf '%s' "${q}" | grep -Eqi '^tool:[[:space:]]*'; then
    run_tool "${q}"
    exit 0
  fi

  [[ -x "${EVID_ONLY}" ]] || { err "missing executable: ${EVID_ONLY}"; exit 20; }
  "${EVID_ONLY}" "${q}"
}

main "$@"
