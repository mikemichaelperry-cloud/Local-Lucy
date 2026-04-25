#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DEFAULT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"
ROOT="${LUCY_ROOT:-$ROOT_DEFAULT}"
CFG="${ROOT}/config"
TOOLS="${ROOT}/tools/internet"
OUT="${ROOT}/evidence"

if [[ $# -ne 1 ]]; then
  echo "ERR: usage: fetch_evidence_test.sh URL_KEY" >&2
  exit 2
fi

KEY="$1"

GENERATED_ALLOWLIST="${CFG}/trust/generated/allowlist_fetch.txt"
LEGACY_TRUSTED="${CFG}/trusted_domains.yaml"
TRUST_ARGS=()
if [[ -s "${GENERATED_ALLOWLIST}" ]]; then
  TRUST_ARGS=(--allowlist "${GENERATED_ALLOWLIST}")
elif [[ -f "${LEGACY_TRUSTED}" ]]; then
  TRUST_ARGS=(--trusted "${LEGACY_TRUSTED}")
else
  echo "ERR: missing trust config (generated allowlist or trusted_domains.yaml)" >&2
  exit 3
fi

python3 "${TOOLS}/fetch_url.py" \
  --key "${KEY}" \
  --url-map "${CFG}/url_map_tests.yaml" \
  "${TRUST_ARGS[@]}" \
  --policy "${CFG}/evidence_policy.yaml" \
  --out "${OUT}"
