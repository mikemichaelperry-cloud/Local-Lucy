#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${LUCY_ROOT:-$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)}"
CATALOG="${ROOT}/config/trust/trust_catalog.yaml"
FETCH_ALLOWLIST="${ROOT}/config/trust/generated/allowlist_fetch.txt"

[[ -s "${CATALOG}" ]] || { echo "ERR: missing catalog: ${CATALOG}" >&2; exit 2; }
[[ -s "${FETCH_ALLOWLIST}" ]] || { echo "ERR: missing fetch allowlist: ${FETCH_ALLOWLIST}" >&2; exit 2; }

python3 - "${CATALOG}" "${FETCH_ALLOWLIST}" <<'PY'
import sys
from pathlib import Path

catalog_path = Path(sys.argv[1])
fetch_path = Path(sys.argv[2])

fetch_domains = set()
for raw in fetch_path.read_text(encoding="utf-8", errors="ignore").splitlines():
    s = raw.strip().lower().rstrip(".")
    if not s or s.startswith("#"):
        continue
    if s.startswith("www."):
        s = s[4:]
    fetch_domains.add(s)

rows = []
in_domains = False
cur_domain = None
tier = None
categories = []
for raw in catalog_path.read_text(encoding="utf-8", errors="ignore").splitlines():
    line = raw.rstrip("\n")
    s = line.strip()
    if not s or s.startswith("#"):
        continue
    indent = len(line) - len(line.lstrip(" "))
    if indent == 0 and s == "domains:":
        in_domains = True
        continue
    if not in_domains:
        continue
    if indent == 2 and s.endswith(":"):
        if cur_domain and "medical" in categories:
            d = cur_domain.lower().rstrip(".")
            if d.startswith("www."):
                d = d[4:]
            rows.append((d, tier if tier is not None else "", "medical", "1" if d in fetch_domains else "0"))
        cur_domain = s[:-1].strip()
        tier = None
        categories = []
        continue
    if cur_domain is None:
        continue
    if indent == 4 and s.startswith("tier:"):
        try:
            tier = int(s.split(":", 1)[1].strip())
        except Exception:
            tier = None
        continue
    if indent == 4 and s.startswith("categories:"):
        v = s.split(":", 1)[1].strip()
        if v.startswith("[") and v.endswith("]"):
            inner = v[1:-1].strip()
            categories = [x.strip().strip('"').strip("'") for x in inner.split(",") if x.strip()]
        else:
            categories = []

if cur_domain and "medical" in categories:
    d = cur_domain.lower().rstrip(".")
    if d.startswith("www."):
        d = d[4:]
    rows.append((d, tier if tier is not None else "", "medical", "1" if d in fetch_domains else "0"))

rows.sort(key=lambda x: x[0])
print("domain\ttier\tcategory\tincluded_in_allowlist_fetch")
for row in rows:
    print("\t".join(str(x) for x in row))
PY
