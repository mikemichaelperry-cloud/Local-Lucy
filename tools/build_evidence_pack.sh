#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DEFAULT="$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)"
ROOT="${LUCY_ROOT:-$ROOT_DEFAULT}"
LATPROF_LIB="${ROOT}/tools/router/latency_profile.sh"
if [[ -f "${LATPROF_LIB}" ]]; then
  # shellcheck disable=SC1090
  source "${LATPROF_LIB}"
else
  latprof_now_ms(){ date +%s000; }
  latprof_append(){ return 0; }
fi

STATE_DIR="${LUCY_STATE_DIR:-$HOME/lucy/state}"
CACHE_DIR="${LUCY_CACHE_DIR:-$HOME/lucy/cache/evidence}"
TOOLS_DIR="${LUCY_TOOLS_DIR:-$HOME/lucy/tools}"

SESSION_ID="${LUCY_SESSION_ID:-default}"
STATE_FILE="$STATE_DIR/evidence_session_${SESSION_ID}.json"

FETCH_KEY="$TOOLS_DIR/fetch_key.sh"
FETCH_JOBS="${LUCY_EVIDENCE_FETCH_JOBS:-4}"

OUT_DIR="${1:-$CACHE_DIR/pack_${SESSION_ID}}"
EVIDENCE_FILE="$OUT_DIR/evidence_pack.txt"
DOMAINS_FILE="$OUT_DIR/domains.txt"

mkdir -p "$OUT_DIR"

usage() {
  cat <<'USAGE'
Usage:
  build_evidence_pack.sh [OUT_DIR]
Env:
  LUCY_SESSION_ID
  LUCY_STATE_DIR
  LUCY_CACHE_DIR
USAGE
}

require_state() {
  if [ ! -f "$STATE_FILE" ]; then
    echo "ERROR: missing state file: $STATE_FILE" >&2
    exit 2
  fi
  if [ ! -x "$FETCH_KEY" ]; then
    echo "ERROR: missing fetch adapter: $FETCH_KEY" >&2
    exit 2
  fi
}

extract_keys_from_state() {
  # Very strict extraction for our known JSON shape:
  # {"session_id":"...","keys":["a","b"],...}
  sed -n 's/.*"keys":\[\(.*\)\].*/\1/p' "$STATE_FILE" \
    | tr -d ' ' \
    | sed -e 's/^"//' -e 's/"$//' -e 's/","/\n/g' \
    | sed '/^$/d'
}

sha256_str() {
  printf "%s" "$1" | sha256sum | awk '{print $1}'
}

normalize_fetch_jobs() {
  local jobs="${FETCH_JOBS}"
  if ! [[ "${jobs}" =~ ^[0-9]+$ ]] || [[ "${jobs}" -lt 1 ]]; then
    jobs=1
  fi
  printf '%s' "${jobs}"
}

fetch_item_worker() {
  local key="$1" item_id="$2" item_txt="$3" item_meta="$4" ts="$5" worker_dir="$6"
  local tmp_err tmp_txt tmp_meta status_file latency_file dom fetch_meta fetch_ms

  tmp_err="${worker_dir}/${item_id}.err"
  tmp_txt="${worker_dir}/${item_id}.txt.tmp"
  tmp_meta="${worker_dir}/${item_id}.meta.tmp"
  status_file="${worker_dir}/${item_id}.status"
  latency_file="${worker_dir}/${item_id}.latency"

  fetch_ms="$(latprof_now_ms)"
  if ! "$FETCH_KEY" "$key" > "$tmp_txt" 2> "$tmp_err"; then
    printf '%s\n' "$(( $(latprof_now_ms) - fetch_ms ))" > "$latency_file"
    printf '%s\n' "FAIL" > "$status_file"
    rm -f "$tmp_txt" "$tmp_meta"
    return 0
  fi
  printf '%s\n' "$(( $(latprof_now_ms) - fetch_ms ))" > "$latency_file"

  dom="$(grep -E '^DOMAIN=' "$tmp_err" | head -n 1 | sed 's/^DOMAIN=//')"
  fetch_meta="$(grep -E '^FETCH_META ' "$tmp_err" | tail -n 1 || true)"
  : "${dom:=unknown}"
  if [[ -n "$fetch_meta" ]]; then
    printf "%s\n" "KEY=$key" "DOMAIN=$dom" "FETCH_UTC=$ts" "$fetch_meta" > "$tmp_meta"
  else
    printf "%s\n" "KEY=$key" "DOMAIN=$dom" "FETCH_UTC=$ts" > "$tmp_meta"
  fi

  mv "$tmp_txt" "$item_txt"
  mv "$tmp_meta" "$item_meta"
  printf '%s\n' "OK" > "$status_file"
}

wait_for_jobs() {
  local pid
  for pid in "$@"; do
    wait "$pid"
  done
}

main() {
  local lat_build_total_start_ms lat_build_keys_start_ms lat_build_fetch_loop_start_ms
  local lat_build_finalize_start_ms keys ts fetched_any worker_dir fetch_jobs
  local key item_id item_txt item_meta dom fetch_meta_line worker_err worker_status
  local worker_latency current_batch_fetches fetch_ms
  local -a worker_pids=()

  lat_build_total_start_ms="$(latprof_now_ms)"
  require_state

  : > "$EVIDENCE_FILE"
  : > "$DOMAINS_FILE"

  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  worker_dir="${OUT_DIR}/.fetch_workers"
  fetch_jobs="$(normalize_fetch_jobs)"
  mkdir -p "${worker_dir}"

  lat_build_keys_start_ms="$(latprof_now_ms)"
  keys="$(extract_keys_from_state || true)"
  latprof_append "build_evidence_pack" "extract_keys" "$(( $(latprof_now_ms) - lat_build_keys_start_ms ))"
  if [ -z "$keys" ]; then
    echo "ERROR: no keys in session (evidence_session.sh add ...)" >&2
    exit 2
  fi

  echo "PACK_UTC=$ts" >> "$EVIDENCE_FILE"
  echo "SESSION_ID=$SESSION_ID" >> "$EVIDENCE_FILE"
  echo "----" >> "$EVIDENCE_FILE"

  fetched_any=0
  lat_build_fetch_loop_start_ms="$(latprof_now_ms)"
  while IFS= read -r key; do
    [ -z "$key" ] && continue

    item_id="$(sha256_str "$key")"
    item_txt="$OUT_DIR/item_${item_id}.txt"
    item_meta="$OUT_DIR/item_${item_id}.meta"

    if [ ! -f "$item_txt" ] || [ ! -f "$item_meta" ]; then
      fetch_item_worker "$key" "$item_id" "$item_txt" "$item_meta" "$ts" "$worker_dir" &
      worker_pids+=("$!")
      if [[ "${#worker_pids[@]}" -ge "${fetch_jobs}" ]]; then
        wait_for_jobs "${worker_pids[@]}"
        worker_pids=()
      fi
    fi
  done <<< "$keys"

  if [[ "${#worker_pids[@]}" -gt 0 ]]; then
    wait_for_jobs "${worker_pids[@]}"
  fi

  while IFS= read -r key; do
    [ -z "$key" ] && continue

    item_id="$(sha256_str "$key")"
    item_txt="$OUT_DIR/item_${item_id}.txt"
    item_meta="$OUT_DIR/item_${item_id}.meta"
    worker_err="${worker_dir}/${item_id}.err"
    worker_status="${worker_dir}/${item_id}.status"
    worker_latency="${worker_dir}/${item_id}.latency"

    if [[ -f "${worker_latency}" ]]; then
      fetch_ms="$(cat "${worker_latency}" 2>/dev/null || printf '0')"
      latprof_append "build_evidence_pack" "fetch_key" "${fetch_ms}"
    fi

    if [[ -f "${worker_status}" ]] && ! grep -Fxq "OK" "${worker_status}"; then
      echo "WARN: fetch failed for key: $key" >&2
      cat "${worker_err}" >&2 || true
      rm -f "${worker_err}" "${worker_status}" "${worker_latency}" "${item_txt}" "${item_meta}"
      continue
    fi

    rm -f "${worker_err}" "${worker_status}" "${worker_latency}"
    dom="$(grep -E '^DOMAIN=' "$item_meta" | head -n 1 | sed 's/^DOMAIN=//')"
    fetch_meta_line="$(grep -E '^FETCH_META ' "$item_meta" | tail -n 1 || true)"
    printf "%s\n" "$dom" >> "$DOMAINS_FILE"
    fetched_any=1

    echo "BEGIN_EVIDENCE_ITEM" >> "$EVIDENCE_FILE"
    echo "KEY=$key" >> "$EVIDENCE_FILE"
    echo "DOMAIN=$dom" >> "$EVIDENCE_FILE"
    echo "FETCH_UTC=$ts" >> "$EVIDENCE_FILE"
    if [[ -n "$fetch_meta_line" ]]; then
      echo "$fetch_meta_line" >> "$EVIDENCE_FILE"
    fi
    echo "----" >> "$EVIDENCE_FILE"
    sed -E 's#https?://[^[:space:]]+##g' "$item_txt" >> "$EVIDENCE_FILE"
    echo "" >> "$EVIDENCE_FILE"
    echo "END_EVIDENCE_ITEM" >> "$EVIDENCE_FILE"
    echo "====" >> "$EVIDENCE_FILE"

  done <<< "$keys"
  latprof_append "build_evidence_pack" "fetch_loop" "$(( $(latprof_now_ms) - lat_build_fetch_loop_start_ms ))"

  if [[ "$fetched_any" -eq 0 ]]; then
    echo "ERROR: no evidence items fetched" >&2
    exit 2
  fi

  # Unique domains list for plurality checks
  lat_build_finalize_start_ms="$(latprof_now_ms)"
  sort -u "$DOMAINS_FILE" > "$DOMAINS_FILE.tmp"
  mv "$DOMAINS_FILE.tmp" "$DOMAINS_FILE"
  latprof_append "build_evidence_pack" "finalize_pack" "$(( $(latprof_now_ms) - lat_build_finalize_start_ms ))"
  latprof_append "build_evidence_pack" "total" "$(( $(latprof_now_ms) - lat_build_total_start_ms ))"
  rm -rf "${worker_dir}"

  echo "OK: built pack: $EVIDENCE_FILE"
  echo "OK: domains: $DOMAINS_FILE"
}

main
