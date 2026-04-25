#!/usr/bin/env bash
set -euo pipefail

URL="${1:-http://127.0.0.1:8080/}"

# Already up?
if curl -fsS --max-time 2 "$URL" >/dev/null 2>&1; then
  exit 0
fi

# Try to start/restart container
if command -v docker >/dev/null 2>&1; then
  if docker ps -a --format '{{.Names}}' | grep -qx 'lucy-searxng'; then
    docker start lucy-searxng >/dev/null 2>&1 || true
    docker restart lucy-searxng >/dev/null 2>&1 || true
  fi
fi

# Wait briefly
for _ in 1 2 3 4 5; do
  if curl -fsS --max-time 2 "$URL" >/dev/null 2>&1; then
    exit 0
  fi
  sleep 1
done

exit 1
