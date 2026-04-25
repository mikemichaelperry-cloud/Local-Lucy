#!/usr/bin/env bash
set -euo pipefail

detect_root() {
  local env_root home root script_root
  env_root="${LUCY_ROOT:-}"
  if [[ -n "${env_root}" ]]; then
    if [[ ! -d "${env_root}" ]]; then
      echo "ERR: LUCY_ROOT does not exist: ${env_root}" >&2
      exit 1
    fi
    if [[ ! -f "${env_root}/lucy_chat.sh" && ! -d "${env_root}/tools" && ! -d "${env_root}/snapshots" ]]; then
      echo "ERR: LUCY_ROOT failed marker check: ${env_root}" >&2
      exit 1
    fi
    printf "%s\n" "${env_root}"
    return 0
  fi
  script_root="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
  if [[ -f "${script_root}/lucy_chat.sh" || -d "${script_root}/tools" || -d "${script_root}/snapshots" ]]; then
    printf "%s\n" "$script_root"
    return 0
  fi
  home="${HOME:-}"
  if [[ -d "${home}/lucy" ]]; then
    root="${home}/lucy"
  else
    echo "ERR: could not determine ROOT" >&2
    exit 1
  fi

  if [[ ! -f "${root}/lucy_chat.sh" && ! -d "${root}/tools" && ! -d "${root}/snapshots" ]]; then
    echo "ERR: ROOT failed marker check: ${root}" >&2
    exit 1
  fi
  printf "%s\n" "$root"
}

ROOT="$(detect_root)"
GEN="${ROOT}/tools/trust/generate_trust_lists.py"
OUT_DIR="${ROOT}/config/trust/generated"
POLICY="${ROOT}/config/trust/policy.yaml"

[[ -f "$GEN" ]] || { echo "ERR: missing generator: $GEN" >&2; exit 1; }
[[ -f "$POLICY" ]] || { echo "ERR: missing policy file: $POLICY" >&2; exit 1; }
echo "OK: policy present"

python3 "$GEN"
echo "OK: generator ran"
python3 "$GEN" --check
echo "OK: generator check clean"

FILES=(
  "allowlist_tier1.txt"
  "allowlist_tier2.txt"
  "allowlist_tier3.txt"
  "allowlist_all_tier12.txt"
  "allowlist_all.txt"
  "allowlist_fetch.txt"
  "news_israel.txt"
  "news_world.txt"
  "policy_global.txt"
  "news_israel_runtime.txt"
  "news_world_runtime.txt"
  "policy_global_runtime.txt"
  "engineering.txt"
  "engineering_runtime.txt"
  "medical.txt"
  "medical_runtime.txt"
  "finance.txt"
  "finance_runtime.txt"
  "vet.txt"
  "vet_runtime.txt"
  "ai.txt"
  "ai_runtime.txt"
)

for f in "${FILES[@]}"; do
  p="${OUT_DIR}/${f}"
  [[ -f "$p" ]] || { echo "ERR: missing generated file: $p" >&2; exit 1; }
  if [[ "$f" == "allowlist_fetch.txt" && ! -s "$p" ]]; then
    echo "ERR: generated fetch allowlist is empty: $p" >&2
    exit 1
  fi

  LC_ALL=C sort -c "$p"
  echo "OK: sorted ${f}"

  if awk 'seen[$0]++{print $0; found=1; exit} END{exit(found?0:1)}' "$p" >/dev/null 2>&1; then
    echo "ERR: duplicate entries in ${f}" >&2
    exit 1
  fi
  echo "OK: unique ${f}"

  if grep -n '[A-Z]' "$p" >/dev/null 2>&1; then
    echo "ERR: uppercase entry found in ${f}" >&2
    exit 1
  fi
  echo "OK: lowercase ${f}"
done

if [[ -f "${ROOT}/config/trusted_sources_catalog.tsv" && -f "${ROOT}/config/trusted_domains.yaml" ]]; then
  if ! grep -q 'GENERATED FILE - DO NOT EDIT' "${ROOT}/config/trusted_sources_catalog.tsv" 2>/dev/null; then
    echo "ERR: stable legacy catalog missing generated banner: ${ROOT}/config/trusted_sources_catalog.tsv" >&2
    exit 1
  fi
  python3 - "${ROOT}/config/trusted_domains.yaml" <<'PY' | LC_ALL=C sort -c
import sys
in_exact=False
for line in open(sys.argv[1], encoding="utf-8", errors="ignore"):
    s=line.rstrip("\n")
    t=s.strip()
    if t.startswith("exact:"):
        in_exact=True
        continue
    if t.startswith("subdomains:"):
        in_exact=False
        continue
    if in_exact and t.startswith("- "):
        print(t[2:].strip())
PY
  echo "OK: sorted trusted_domains.yaml exact entries"
  if python3 - "${ROOT}/config/trusted_domains.yaml" <<'PY' >/dev/null 2>&1
import sys
in_exact=False
seen=set()
for line in open(sys.argv[1], encoding="utf-8", errors="ignore"):
    t=line.strip()
    if t.startswith("exact:"):
        in_exact=True
        continue
    if t.startswith("subdomains:"):
        in_exact=False
        continue
    if in_exact and t.startswith("- "):
        v=t[2:].strip()
        if v in seen:
            raise SystemExit(0)
        seen.add(v)
raise SystemExit(1)
PY
  then
    echo "ERR: duplicate exact entries in trusted_domains.yaml" >&2
    exit 1
  fi
  echo "OK: unique trusted_domains.yaml exact entries"
fi

echo "OK: trust list verification complete"
