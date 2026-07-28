#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${LUCY_UI_ROOT:-$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)}"
REPO_ROOT="$(CDPATH= cd -- "$ROOT/.." && pwd)"
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
    cd "$REPO_ROOT"
    # Track only committed files under the UI tree so generated runtime
    # artifacts do not drift between local development and CI.
    git ls-files \
      ui-v10/app/ \
      ui-v10/tests/ \
      ui-v10/tools/ \
      2>/dev/null \
      | sed 's#^ui-v10/##' \
      | grep -vE '^SHA256SUMS(\.clean)?$' \
      | grep -vE '\.pyc$' \
      | grep -vE '\.(bak|tmp|fixbak)\.' \
      | grep -vE '\.BROKEN\.' \
      | grep -v '__pycache__/' \
      | grep -v '/\.venv/' \
      | grep -v '/\.pytest_cache/' \
      | grep -v '/build/' \
      | grep -v '/vendor/' \
      | grep -v '/\.git/' \
      | grep -v '/\.devops/' \
      | grep -v '/\.idea/' \
      | grep -v '\.DS_Store$' \
      | while IFS= read -r rel; do
          # Exclude symlinks (e.g. tools/router -> app/backend/router) so
          # sha256sum does not try to hash a directory link.
          if [ -L "ui-v10/$rel" ]; then
            continue
          fi
          printf '%s\n' "$rel"
        done
  ) \
    | sort
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
