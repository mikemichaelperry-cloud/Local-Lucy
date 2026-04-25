#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${LUCY_ROOT:-$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)}"
MANIFEST="${LUCY_SHA_MANIFEST:-$ROOT/SHA256SUMS.clean}"

usage() {
  cat <<'EOF'
Usage: tools/sha_manifest.sh [regen|check|list]

  regen  Regenerate SHA256SUMS.clean for clean source/config/runtime files
  check  Verify SHA256SUMS.clean
  list   Print tracked file list
EOF
}

collect_files() {
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
      | sed 's#^\./##'
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
  fi
}

verify_manifest() {
  (
    cd "$ROOT"
    sha256sum -c "$MANIFEST"
  )
}

cmd="${1:-check}"
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
