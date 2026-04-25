#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"
TOOL="${ROOT}/tools/news_answer_deterministic.sh"

ok(){ echo "OK: $*"; }
die(){ echo "FAIL: $*" >&2; exit 1; }

[[ -x "${TOOL}" ]] || die "missing executable: ${TOOL}"

TMPD="$(mktemp -d)"
trap 'rm -rf "${TMPD}"' EXIT

digest="${TMPD}/empty.digest"
cat > "${digest}" <<'EOF'
DIGEST_UTC=2026-03-09T16:00:00Z
====
EOF

out="$("${TOOL}" "${digest}" "What are the latest headlines?")"
printf '%s\n' "${out}" | grep -q '^Key items:$' || die "missing key items header"
printf '%s\n' "${out}" | grep -q 'Insufficient evidence from trusted sources.' || die "missing insufficiency message"
if printf '%s\n' "${out}" | grep -q '^Sources:'; then
  die "unexpected empty Sources block"
fi

ok "news deterministic output suppresses empty Sources block"
echo "PASS: test_news_answer_no_empty_sources_block"
