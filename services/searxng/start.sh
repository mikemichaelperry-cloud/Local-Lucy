#!/usr/bin/env bash
# Local Lucy v10 — SearXNG launcher with auto-generated secret
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SETTINGS="${SCRIPT_DIR}/searxng/settings.yml"

# Generate a random secret if the current one is the placeholder or missing
if [ ! -f "$SETTINGS" ] || grep -q 'secret_key: "CHANGE_ME"' "$SETTINGS" 2>/dev/null; then
    echo "[searxng] Generating fresh secret_key..."
    NEW_SECRET="$(openssl rand -hex 32)"
    if [ -f "$SETTINGS" ]; then
        sed -i "s/secret_key: \"CHANGE_ME\"/secret_key: \"${NEW_SECRET}\"/" "$SETTINGS"
    else
        mkdir -p "$(dirname "$SETTINGS")"
        cat > "$SETTINGS" <<EOF
use_default_settings: true

server:
  limiter: false
  secret_key: "${NEW_SECRET}"

search:
  formats: [html, json, rss, csv]
  # patched-by-lucy-internet-v0
EOF
    fi
fi

cd "$SCRIPT_DIR"
docker compose up -d
