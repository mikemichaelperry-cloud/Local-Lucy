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
CONF_DIR="${LUCY_CONF_DIR:-$ROOT/config}"
KEYMAP="$CONF_DIR/evidence_keymap_v1.tsv"

FETCH_URL_TOOL="${LUCY_FETCH_URL_TOOL:-$ROOT/tools/fetch_url_allowlisted.sh}"

usage() {
  cat <<'USAGE'
Usage:
  fetch_key.sh KEY
Env:
  LUCY_CONF_DIR
  LUCY_FETCH_URL_TOOL (default: <root>/tools/fetch_url_allowlisted.sh)
Output:
  Writes extracted text to stdout.
  Writes metadata lines (DOMAIN=...) to stderr.
USAGE
}

require_files() {
  if [ ! -x "$FETCH_URL_TOOL" ]; then
    echo "ERROR: missing fetch tool (set LUCY_FETCH_URL_TOOL): $FETCH_URL_TOOL" >&2
    exit 2
  fi
}

lookup_dynamic_medical_key() {
  local k source candidate url dom
  k="$1"
  if [[ ! "${k}" =~ ^medical_dynamic_(medlineplus|dailymed|pubmed)_([a-z0-9-]{2,32})$ ]]; then
    return 1
  fi
  source="${BASH_REMATCH[1]}"
  candidate="${BASH_REMATCH[2]}"
  case "${source}" in
    medlineplus)
      url="https://medlineplus.gov/search/?query=${candidate}"
      dom="medlineplus.gov"
      ;;
    dailymed)
      url="https://dailymed.nlm.nih.gov/dailymed/search.cfm?query=${candidate}"
      dom="dailymed.nlm.nih.gov"
      ;;
    pubmed)
      url="https://pubmed.ncbi.nlm.nih.gov/?term=${candidate}"
      dom="pubmed.ncbi.nlm.nih.gov"
      ;;
    *)
      return 1
      ;;
  esac
  printf '%s\t%s\n' "${url}" "${dom}"
}

lookup_key() {
  # prints: url<TAB>domain_label
  local k="$1"
  local dynamic_row
  dynamic_row="$(lookup_dynamic_medical_key "$k" || true)"
  if [ -n "${dynamic_row}" ]; then
    printf '%s\n' "${dynamic_row}"
    return 0
  fi
  if [ ! -f "$KEYMAP" ]; then
    return 1
  fi
  awk -F'\t' -v key="$k" '
    $0 ~ /^#/ { next }
    NF >= 3 && $1 == key { print $2 "\t" $3; found=1; exit }
    END { if (!found) exit 1 }
  ' "$KEYMAP"
}

main() {
  if [ $# -ne 1 ]; then
    usage
    exit 2
  fi

  require_files

  key="$1"
  row="$(lookup_key "$key" || true)"
  if [ -z "$row" ]; then
    echo "ERROR: unknown key: $key" >&2
    exit 2
  fi

  url="$(printf "%s" "$row" | awk -F'\t' '{print $1}')"
  dom="$(printf "%s" "$row" | awk -F'\t' '{print $2}')"

  echo "KEY=$key" >&2
  echo "URL=$url" >&2
  echo "DOMAIN=$dom" >&2

  # Fetch tool must be deterministic and allowlisted.
  # It must output extracted text to stdout (no HTML, no prompts).
  lat_fetch_key_start_ms="$(latprof_now_ms)"
  "$FETCH_URL_TOOL" "$url"
  latprof_append "fetch_key" "fetch_url_tool" "$(( $(latprof_now_ms) - lat_fetch_key_start_ms ))"
}

main "$@"
