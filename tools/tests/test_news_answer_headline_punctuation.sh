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

digest="${TMPD}/news.digest"
cat > "${digest}" <<'EOF'
DIGEST_UTC=2026-04-04T08:00:00Z
====
DOMAIN: nytimes.com
DATE: Sat, 04 Apr 2026 07:54:02 +0000
TITLE: Iran War Live Updates: U.S. Forces Search for Missing Airman After Iran Downs Jet
DESC: Desc one
----
DOMAIN: bbc.co.uk
DATE: Sat, 04 Apr 2026 06:42:48 GMT
TITLE: Artemis II crew now halfway to Moon as they face pace challenge of Easter
DESC: Desc two
----
EOF

out="$("${TOOL}" "${digest}" "What about the latest world news?")"
printf '%s\n' "${out}" | grep -Eq '^\- \[nytimes\.com\].*\.$' || die "expected nytimes headline bullet to end with punctuation"
printf '%s\n' "${out}" | grep -Eq '^\- \[bbc\.co\.uk\].*\.$' || die "expected bbc headline bullet to end with punctuation"
printf '%s\n' "${out}" | grep -Eq '^\- nytimes\.com$' || die "expected source domain line to remain unpunctuated"
printf '%s\n' "${out}" | grep -Eq '^\- bbc\.co\.uk$' || die "expected source domain line to remain unpunctuated"

ok "news deterministic output terminates headline bullets without altering source-domain bullets"
echo "PASS: test_news_answer_headline_punctuation"
