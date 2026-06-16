#!/usr/bin/env bash
# packaging/debian/build_deb.sh — Build a Debian package for Local Lucy v10.
#
# The package installs the application source to /opt/local-lucy/ and provides
# /usr/local/bin/local-lucy and /usr/local/bin/local-lucy-chat symlinks.
# The Python venv is created on the target machine by the postinst script to
# keep the .deb artifact small enough for GitHub Releases.

set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)"
VERSION_FILE="$REPO_ROOT/VERSION"

cd "$REPO_ROOT"

# -----------------------------------------------------------------------------
# Determine package version
# -----------------------------------------------------------------------------
GIT_VERSION="$(git describe --tags --match 'v*' --abbrev=0 2>/dev/null || true)"
if [ -n "$GIT_VERSION" ]; then
    VERSION="${GIT_VERSION#v}"
else
    VERSION="$(cat "$VERSION_FILE")"
fi
# Debian upstream version must not contain a hyphen as the first separator-ish
# character, so map pre-release separators to '~' (Debian's "earlier than").
# Use sed for the substitution to avoid bash tilde-expansion in the replacement.
VERSION="$(printf '%s' "$VERSION" | sed 's/-/~/g')"

PACKAGE="local-lucy"
ARCH="amd64"
DEB_NAME="${PACKAGE}_${VERSION}_${ARCH}.deb"

# -----------------------------------------------------------------------------
# Staging area
# -----------------------------------------------------------------------------
STAGING="$(mktemp -d)"
trap 'rm -rf "$STAGING"' EXIT

PKGROOT="$STAGING/${PACKAGE}_${VERSION}_${ARCH}"
mkdir -p "$PKGROOT/DEBIAN"
mkdir -p "$PKGROOT/opt/local-lucy"
mkdir -p "$PKGROOT/usr/local/bin"

# -----------------------------------------------------------------------------
# Copy source tree (excluding build/runtime artifacts and the venv)
# -----------------------------------------------------------------------------
echo "[build_deb] Copying source tree to staging area..."
cd "$REPO_ROOT"
tar -c \
    --exclude='.git' \
    --exclude='.github' \
    --exclude='packaging' \
    --exclude='ui_debug.log' \
    --exclude='ui-v10/.venv' \
    --exclude='runtime/state' \
    --exclude='tmp' \
    --exclude='__pycache__' \
    --exclude='.pytest_cache' \
    --exclude='*.pyc' \
    --exclude='.env' \
    . | tar -x -C "$PKGROOT/opt/local-lucy"

# Ensure launchers are executable
chmod 0755 "$PKGROOT/opt/local-lucy/START_LUCY.sh"
chmod 0755 "$PKGROOT/opt/local-lucy/lucy_chat.sh"

# -----------------------------------------------------------------------------
# Symlinks and Debian metadata
# -----------------------------------------------------------------------------
echo "[build_deb] Creating symlinks..."
ln -sf /opt/local-lucy/START_LUCY.sh "$PKGROOT/usr/local/bin/local-lucy"
ln -sf /opt/local-lucy/lucy_chat.sh "$PKGROOT/usr/local/bin/local-lucy-chat"

cp "$REPO_ROOT/packaging/debian/DEBIAN/postinst" "$PKGROOT/DEBIAN/postinst"
chmod 0755 "$PKGROOT/DEBIAN/postinst"

INSTALLED_SIZE="$(du -sk "$PKGROOT/opt" | cut -f1)"
sed -e "s/@VERSION@/$VERSION/" \
    -e "s/@INSTALLED_SIZE@/$INSTALLED_SIZE/" \
    "$REPO_ROOT/packaging/debian/DEBIAN/control" \
    > "$PKGROOT/DEBIAN/control"

# -----------------------------------------------------------------------------
# Build the .deb
# -----------------------------------------------------------------------------
echo "[build_deb] Building $DEB_NAME..."
mkdir -p "$REPO_ROOT/dist"
dpkg-deb --build "$PKGROOT" "$REPO_ROOT/dist/$DEB_NAME"

echo "[build_deb] Package created: $REPO_ROOT/dist/$DEB_NAME"
