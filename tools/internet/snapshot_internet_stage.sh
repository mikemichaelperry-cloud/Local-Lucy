#!/usr/bin/env bash
set -euo pipefail

ROOT="$HOME/lucy"
STAMP="$(date -Is)"
SNAP="$ROOT/snapshots/dev-evidence-internet-hardened-v1"

mkdir -p "$SNAP"

cp -a "$ROOT/config" "$SNAP/"
cp -a "$ROOT/tools/internet" "$SNAP/tools_internet"
cp -a "$ROOT/tools/internet/tests_run_limit.sh" "$SNAP/" 2>/dev/null || true

cat > "$SNAP/README.txt" <<EOF
Snapshot: dev-evidence-internet-hardened-v1
Created: $STAMP

Stage: Deterministic Envelope + Evidence-Gated Internet (hardened)

Includes:
- URL-key mapping (url_map.yaml) + test split (url_map_tests.yaml)
- HTTPS-only allowlist
- DNS-to-private block
- Redirect validation (count + allowlist + DNS-to-private)
- Content-type allowlist + content sniffing
- Size/time limits
- Raw + extracted + meta + sha256 retention
- Declared-domain match enforcement
- Limit test runner included

EOF

( cd "$SNAP" && find . -type f ! -name 'SHA256SUMS.clean' -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS.clean )

echo "SNAPSHOT_WRITTEN $SNAP"
