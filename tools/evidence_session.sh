#!/usr/bin/env bash
set -euo pipefail

CONF_DIR="${LUCY_CONF_DIR:-$HOME/lucy/config}"
STATE_DIR="${LUCY_STATE_DIR:-$HOME/lucy/state}"
KEYS_FILE="$CONF_DIR/evidence_keys_allowlist.txt"

mkdir -p "$STATE_DIR"

SESSION_ID="${LUCY_SESSION_ID:-default}"
STATE_FILE="$STATE_DIR/evidence_session_${SESSION_ID}.json"

usage() {
  cat <<'USAGE'
Usage:
  evidence_session.sh clear
  evidence_session.sh add KEY [KEY...]
  evidence_session.sh list
Env:
  LUCY_CONF_DIR (default: $HOME/lucy/config)
  LUCY_STATE_DIR (default: $HOME/lucy/state)
  LUCY_SESSION_ID (default: default)
USAGE
}

require_keys_file() {
  if [ ! -f "$KEYS_FILE" ]; then
    echo "ERROR: missing allowlist: $KEYS_FILE" >&2
    exit 2
  fi
}

is_dynamic_medical_key() {
  local k
  k="$1"
  [[ "${k}" =~ ^medical_dynamic_(medlineplus|dailymed|pubmed)_[a-z0-9-]{2,32}$ ]]
}

init_state_if_missing() {
  if [ ! -f "$STATE_FILE" ]; then
    printf "%s\n" "{\"session_id\":\"$SESSION_ID\",\"keys\":[],\"updated_utc\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}" > "$STATE_FILE"
  fi
}

json_escape() {
  sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'
}

is_allowed_key() {
  # exact line match in allowlist
  local k
  k="$1"
  if is_dynamic_medical_key "$k"; then
    return 0
  fi
  grep -Fxq "$k" "$KEYS_FILE"
}

clear_session() {
  printf "%s\n" "{\"session_id\":\"$SESSION_ID\",\"keys\":[],\"updated_utc\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}" > "$STATE_FILE"
  echo "OK: cleared"
}

list_session() {
  init_state_if_missing
  cat "$STATE_FILE"
}

add_keys() {
  init_state_if_missing

  if [ $# -lt 1 ]; then
    echo "ERROR: add requires at least one KEY" >&2
    exit 2
  fi

  local k need_allowlist
  need_allowlist=0
  for k in "$@"; do
    if ! is_dynamic_medical_key "$k"; then
      need_allowlist=1
      break
    fi
  done
  if [ "${need_allowlist}" -eq 1 ]; then
    require_keys_file
  fi

  # Read existing keys (very simple JSON extraction, deterministic for our format)
  # Expect: ..."keys":[ "a","b" ]... OR empty.
  local existing
  existing="$(sed -n 's/.*"keys":\[\(.*\)\].*/\1/p' "$STATE_FILE" | tr -d ' ')"
  # existing is something like: "a","b" or empty

  local new_csv="$existing"
  for k in "$@"; do
    if ! is_allowed_key "$k"; then
      echo "ERROR: key not allowlisted: $k" >&2
      exit 2
    fi

    # prevent duplicates: check for exact quoted token in csv
    if printf "%s" "$new_csv" | grep -Fq "\"$k\""; then
      continue
    fi

    if [ -z "$new_csv" ]; then
      new_csv="\"$k\""
    else
      new_csv="$new_csv,\"$k\""
    fi
  done

  printf "%s\n" "{\"session_id\":\"$SESSION_ID\",\"keys\":[${new_csv}],\"updated_utc\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}" > "$STATE_FILE"
  echo "OK: added"
}

main() {
  if [ $# -lt 1 ]; then
    usage
    exit 2
  fi

  cmd="$1"
  shift

  case "$cmd" in
    clear)
      clear_session
      ;;
    add)
      add_keys "$@"
      ;;
    list)
      list_session
      ;;
    -h|--help)
      usage
      ;;
    *)
      echo "ERROR: unknown command: $cmd" >&2
      usage
      exit 2
      ;;
  esac
}

main "$@"
