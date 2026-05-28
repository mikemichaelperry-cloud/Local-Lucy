#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${LUCY_UI_ROOT:-$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)}"
MANIFEST="${LUCY_UI_SHA_MANIFEST:-$ROOT/SHA256SUMS.clean}"

usage() {
  cat <<'EOF'
Usage: tools/sha_manifest.sh [regen|check|list]

  regen  Regenerate SHA256SUMS.clean for tracked UI source and tests
  check  Verify SHA256SUMS.clean
  list   Print tracked file list
EOF
}

collect_files() {
  (
    cd "$ROOT"
    find \
      ./app \
      ./tests \
      ./tools \
      -type f \
      ! -path "*/__pycache__/*" \
      ! -path "*/.venv/*" \
      ! -path "*/.git/*" \
      ! -name "*.pyc" \
      ! -name "*.tmp" \
      ! -name "*.bak" \
      ! -name "SHA256SUMS.clean" \
      ! -name "SHA256SUMS" \
      -print0
    find \
      . \
      -maxdepth 1 \
      -type f \
      \( -name "*.md" -o -name "*.py" -o -name "*.sh" \) \
      ! -name "SHA256SUMS.clean" \
      ! -name "SHA256SUMS" \
      -print0
  ) \
    | sort -z \
    | xargs -0 -n1 printf '%s\n' \
    | sed 's#^\./##'
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
