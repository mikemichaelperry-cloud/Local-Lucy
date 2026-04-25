#!/usr/bin/env bash
set -euo pipefail

BASE="${LUCY_BASE_DIR:-$HOME/lucy}"
SNAP_NAME="${1:-}"

if [ -z "$SNAP_NAME" ]; then
  echo "Usage: freeze_snapshot.sh SNAPSHOT_NAME"
  exit 2
fi

# Prevent freezing while Lucy is running
if pgrep -f "ollama" >/dev/null 2>&1; then
  echo "ERROR: Ollama appears to be running. Stop Lucy before freezing."
  exit 2
fi

DEST="$BASE/snapshots/$SNAP_NAME"

if [ -e "$DEST" ]; then
  echo "ERROR: Snapshot already exists: $DEST"
  exit 2
fi

mkdir -p "$DEST"

echo "Creating snapshot: $SNAP_NAME"
echo "Source: $BASE"
echo "Destination: $DEST"

rsync -a \
  --exclude 'cache' \
  --exclude 'snapshots' \
  --exclude '*.pyc' \
  --exclude '__pycache__' \
  "$BASE/" "$DEST/"

cd "$DEST"

echo "Generating SHA256SUMS.clean..."
if [[ -x "./tools/sha_manifest.sh" ]]; then
  ./tools/sha_manifest.sh regen >/dev/null
else
  echo "ERROR: missing manifest tool: $DEST/tools/sha_manifest.sh"
  exit 2
fi

echo "Verifying manifest..."
./tools/sha_manifest.sh check > /dev/null

MANI_SHA="$(sha256sum SHA256SUMS.clean | awk '{print $1}')"

echo "Recording in STATELOG..."
echo "SNAPSHOT $SNAP_NAME $(date -Is) SHA256SUMS.clean=$MANI_SHA" >> "$BASE/STATELOG.txt"

echo "Snapshot complete."
echo "Manifest hash: $MANI_SHA"
