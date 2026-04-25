#!/usr/bin/env bash
set -euo pipefail

K="$HOME/lucy/keel/keel.yaml"
if [[ ! -s "$K" ]]; then
  echo "Keel: missing"
  exit 0
fi

hash="$(sha256sum "$K" | awk '{print $1}')"

# helper: find "key: value" allowing leading whitespace; print value only
getv() {
  local key="$1"
  awk -v k="$key" '
    $0 ~ "^[[:space:]]*" k ":[[:space:]]*" {
      sub("^[[:space:]]*" k ":[[:space:]]*", "", $0)
      print $0
      exit
    }' "$K"
}

ver="$(getv version)"
tool="$(getv tool_access)"
inet="$(getv internet_access)"
fsw="$(getv filesystem_write)"

echo "Keel loaded: version=${ver:-?} hash=$hash tool_access=${tool:-?} internet_access=${inet:-?} filesystem_write=${fsw:-?}"
