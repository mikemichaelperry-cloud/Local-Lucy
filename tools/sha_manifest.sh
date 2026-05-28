#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${LUCY_ROOT:-$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)}"

UI_V8_MODE=0
MANIFEST="${LUCY_SHA_MANIFEST:-$ROOT/SHA256SUMS.clean}"

usage() {
  cat <<'EOF'
Usage: tools/sha_manifest.sh [--ui-v10] [regen|check|list]

  --ui-v10  Target ui-v10/SHA256SUMS.clean instead of the root manifest
  regen    Regenerate SHA256SUMS.clean for clean source/config/runtime files
  check    Verify SHA256SUMS.clean
  list     Print tracked file list
EOF
}

collect_files() {
  if [[ "$UI_V8_MODE" -eq 1 ]]; then
    _collect_ui_v8_files
  else
    _collect_root_files
  fi
}

_collect_root_files() {
  (
    cd "$ROOT"
    find \
      ./config \
      ./tools \
      ./runtime \
      ./lucy_chat.sh \
      -type f \
      ! -path "./logs/*" \
      ! -path "./out/*" \
      ! -path "./dev_notes/*" \
      ! -path "./build/*" \
      ! -path "./tools/tmp/*" \
      ! -path "./tools/tests/governor_migration/artifacts/*" \
      ! -path "./vendor/*" \
      ! -path "./runtime/voice/piper-venv/*" \
      ! -path "./runtime/voice/models/*" \
      ! -path "./runtime/voice/whisper.cpp/models/*" \
      ! -path "./config/trusted_domains_tests.yaml" \
      ! -path "./config/url_map_tests_tmp.yaml" \
      ! -path "./runtime/state.json" \
      ! -path "./runtime/Modelfile.local-lucy-mem.generated" \
      ! -path "*/build/*" \
      ! -path "*/vendor/*" \
      ! -path "*/.git/*" \
      ! -path "*/.github/*" \
      ! -path "*/.devops/*" \
      ! -path "*/.idea/*" \
      ! -path "*/.venv/*" \
      ! -path "*/.pytest_cache/*" \
      ! -path "*/__pycache__/*" \
      ! -name "*.pyc" \
      ! -name "*.bak" \
      ! -name "*.bak*" \
      ! -name "*.BROKEN.*" \
      ! -name "*.fixbak.*" \
      ! -name "*.tmp" \
      ! -name ".DS_Store" \
      ! -name "SHA256SUMS.clean" \
      ! -name "SHA256SUMS" \
      ! -name "SHA256SUMS.txt" \
      ! -name "CHECKSUMS_SHA256.txt" \
      -print0 \
      | sort -z \
      | xargs -0 -n1 printf '%s\n' \
      | sed 's#^\.\/##'
  )
}

_collect_ui_v8_files() {
  (
    cd "$ROOT"
    find \
      ./ui-v10/app \
      ./ui-v10/tests \
      ./ui-v10/tools \
      -type f \
      ! -path "*/build/*" \
      ! -path "*/vendor/*" \
      ! -path "*/.git/*" \
      ! -path "*/.github/*" \
      ! -path "*/.devops/*" \
      ! -path "*/.idea/*" \
      ! -path "*/.venv/*" \
      ! -path "*/.pytest_cache/*" \
      ! -path "*/__pycache__/*" \
      ! -name "*.pyc" \
      ! -name "*.bak" \
      ! -name "*.bak*" \
      ! -name "*.BROKEN.*" \
      ! -name "*.fixbak.*" \
      ! -name "*.tmp" \
      ! -name ".DS_Store" \
      ! -name "SHA256SUMS.clean" \
      ! -name "SHA256SUMS" \
      ! -name "SHA256SUMS.txt" \
      ! -name "CHECKSUMS_SHA256.txt" \
      -print0 \
      | sort -z \
      | xargs -0 -n1 printf '%s\n' \
      | sed 's#^\.\/##'
  )
}

regen_manifest() {
  local tmp
  tmp="$(mktemp)"

  (
    cd "$ROOT"
    while IFS= read -r rel; do
      sha256sum "./$rel"
    done < <(collect_files)
  ) > "$tmp"

  mv "$tmp" "$MANIFEST"

  if [[ "$MANIFEST" == "$ROOT/SHA256SUMS.clean" ]]; then
    cp "$MANIFEST" "$ROOT/SHA256SUMS"
  elif [[ "$MANIFEST" == "$ROOT/ui-v10/SHA256SUMS.clean" ]]; then
    cp "$MANIFEST" "$ROOT/ui-v10/SHA256SUMS"
  fi
}

verify_manifest() {
  (
    cd "$ROOT"
    sha256sum -c "$MANIFEST"
  )
}

# Parse optional --ui-v10 flag
cmd="${1:-check}"
if [[ "$cmd" == "--ui-v10" ]]; then
  UI_V8_MODE=1
  MANIFEST="$ROOT/ui-v10/SHA256SUMS.clean"
  cmd="${2:-check}"
fi

case "$cmd" in
  regen)
    regen_manifest
    verify_manifest >/dev/null
    echo "OK: regenerated and verified $MANIFEST"
    ;;
  check)
    verify_manifest
    ;;
  list)
    collect_files
    ;;
  *)
    usage
    exit 2
    ;;
esac
