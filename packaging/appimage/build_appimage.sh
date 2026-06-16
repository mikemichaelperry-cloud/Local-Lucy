#!/usr/bin/env bash
# packaging/appimage/build_appimage.sh — Build an AppImage for Local Lucy v10.
#
# This is a starter script. It expects appimagetool to be available:
#   wget https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage
#   chmod +x appimagetool-x86_64.AppImage
#   sudo mv appimagetool-x86_64.AppImage /usr/local/bin/appimagetool
#
# The AppImage bundles the source tree and a pre-built venv. Because the venv
# contains compiled extensions, it must be built on a system similar to the
# target (Ubuntu 22.04/24.04 recommended for broad glibc compatibility).

set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)"
VERSION_FILE="$REPO_ROOT/VERSION"

# Determine version
GIT_VERSION="$(git describe --tags --match 'v*' --abbrev=0 2>/dev/null || true)"
if [ -n "$GIT_VERSION" ]; then
    VERSION="${GIT_VERSION#v}"
else
    VERSION="$(cat "$VERSION_FILE")"
fi

APPIMAGE_NAME="local-lucy-${VERSION}-x86_64.AppImage"
APPDIR="$REPO_ROOT/dist/AppDir"

# Clean and create AppDir
rm -rf "$APPDIR"
mkdir -p "$APPDIR/opt/local-lucy"
mkdir -p "$APPDIR/usr/share/applications"
mkdir -p "$APPDIR/usr/share/icons/hicolor/256x256/apps"

# Bundle source tree (similar exclusions as the .deb build)
cd "$REPO_ROOT"
tar -c \
    --exclude='.git' \
    --exclude='.github' \
    --exclude='packaging' \
    --exclude='dist' \
    --exclude='ui_debug.log' \
    --exclude='runtime/state' \
    --exclude='tmp' \
    --exclude='__pycache__' \
    --exclude='.pytest_cache' \
    --exclude='*.pyc' \
    --exclude='.env' \
    . | tar -x -C "$APPDIR/opt/local-lucy"

# Ensure venv exists (caller should have run make install first)
if [ ! -x "$APPDIR/opt/local-lucy/ui-v10/.venv/bin/python" ]; then
    echo "ERROR: venv not found. Run 'make install' before building the AppImage." >&2
    exit 1
fi

# Install launcher metadata
cp "$SCRIPT_DIR/AppRun" "$APPDIR/AppRun"
chmod 0755 "$APPDIR/AppRun"
cp "$SCRIPT_DIR/local-lucy.desktop" "$APPDIR/usr/share/applications/"
cp "$APPDIR/usr/share/applications/local-lucy.desktop" "$APPDIR/local-lucy.desktop"

# Placeholder icon (replace with real icon when available)
touch "$APPDIR/usr/share/icons/hicolor/256x256/apps/local-lucy.png"

# Build AppImage
mkdir -p "$REPO_ROOT/dist"
appimagetool "$APPDIR" "$REPO_ROOT/dist/$APPIMAGE_NAME"

echo "[build_appimage] Created: $REPO_ROOT/dist/$APPIMAGE_NAME"
