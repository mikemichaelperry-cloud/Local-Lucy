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
  regen    Regenerate SHA256SUMS.clean for clean source/config files
  check    Verify SHA256SUMS.clean
  list     Print tracked file list
EOF
}

collect_files() {
  if [[ "$UI_V8_MODE" -eq 1 ]]; then
    _collect_ui_v10_files
  else
    _collect_root_files
  fi
}

_collect_root_files() {
  (
    cd "$ROOT"
    # Use git ls-files so the manifest tracks only committed source files and
    # automatically respects .gitignore. This prevents locally-generated runtime
    # artifacts from drifting between developer machines and CI runners.
    git ls-files \
      config/ \
      tools/ \
      scripts/ \
      data/ \
      models/ \
      web_adapter/ \
      tests/ \
      .github/ \
      lucy_chat.sh \
      README.md \
      Architecture.md \
      ARCHITECTURE.md \
      pyproject.toml \
      Makefile \
      CONTRIBUTING.md \
      LICENSE \
      2>/dev/null \
      | grep -vE '^SHA256SUMS(\.clean)?$' \
      | grep -vE '\.pyc$' \
      | grep -vE '\.(bak|tmp| fixbak)\.' \
      | grep -vE '\.BROKEN\.' \
      | grep -v '__pycache__/' \
      | grep -v '/\.venv/' \
      | grep -v '/\.pytest_cache/' \
      | grep -v '/build/' \
      | grep -v '/vendor/' \
      | grep -v '/\.git/' \
      | grep -v '/\.devops/' \
      | grep -v '/\.idea/' \
      | grep -v '\.DS_Store$'
  ) \
    | sort
}

_collect_ui_v10_files() {
  (
    cd "$ROOT"
    # Track only committed UI source/test/tool files.
    git ls-files \
      ui-v10/app/ \
      ui-v10/tests/ \
      ui-v10/tools/ \
      2>/dev/null \
      | grep -vE '^ui-v10/SHA256SUMS(\.clean)?$' \
      | grep -vE '\.pyc$' \
      | grep -vE '\.(bak|tmp| fixbak)\.' \
      | grep -vE '\.BROKEN\.' \
      | grep -v '__pycache__/' \
      | grep -v '/\.venv/' \
      | grep -v '/\.pytest_cache/' \
      | grep -v '/build/' \
      | grep -v '/vendor/' \
      | grep -v '/\.git/' \
      | grep -v '/\.github/' \
      | grep -v '/\.devops/' \
      | grep -v '/\.idea/' \
      | grep -v '\.DS_Store$'
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

# Parse optional --ui-v10 flag. Delegate to the UI-local collector so paths are
# recorded relative to ui-v10/ (e.g. ./app/main.py), not relative to the repo
# root (which would produce broken ./ui-v10/app/main.py entries).
cmd="${1:-check}"
if [[ "$cmd" == "--ui-v10" ]]; then
  UI_CMD="${2:-check}"
  exec "$ROOT/ui-v10/tools/sha_manifest.sh" "$UI_CMD"
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
