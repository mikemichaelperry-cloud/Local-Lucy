#!/usr/bin/env bash
set -euo pipefail
ROOT="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
CAT="$ROOT/config/trust/trust_catalog.yaml"
[[ -f "$CAT" ]] || { echo "ERR: missing trust catalog" >&2; exit 1; }
python3 - "$CAT" <<'PY'
import sys
p=sys.argv[1]
in_domains=False; cur=None; tier=None; req=None; bad=[]
for line in open(p,encoding='utf-8'):
    t=line.rstrip('\n'); s=t.strip()
    if not s or s.startswith('#'): continue
    ind=len(t)-len(t.lstrip(' '))
    if ind==0 and s=='domains:': in_domains=True; continue
    if not in_domains: continue
    if ind==2 and s.endswith(':'):
        if cur and tier==3 and req is not True: bad.append(cur)
        cur=s[:-1].strip(); tier=None; req=None; continue
    if ind==4 and s.startswith('tier:'): tier=int(s.split(':',1)[1].strip())
    if ind==4 and s.startswith('requires_corroboration:'): req=(s.split(':',1)[1].strip()=='true')
if cur and tier==3 and req is not True: bad.append(cur)
if bad:
    raise SystemExit('tier3 without requires_corroboration: ' + ', '.join(bad))
PY
q='Does tadalafil affect arrhythmia risk?'
if [[ -x "$ROOT/tools/router/execute_plan.sh" ]]; then
  out="$(LUCY_ROUTE_CONTROL_MODE=FORCED_OFFLINE "$ROOT/tools/router/execute_plan.sh" "$q" 2>&1 || true)"
else
  out="$(LUCY_ENABLE_INTERNET=0 "$ROOT/lucy_chat.sh" "$q" 2>&1 || true)"
fi
printf '%s\n' "$out" | grep -q '^BEGIN_VALIDATED$' || { echo "ERR: no validated block" >&2; exit 1; }
printf '%s\n' "$out" | grep -q '^Insufficient evidence from trusted sources\.$' || { echo "ERR: no insufficient evidence line" >&2; exit 1; }
echo "PASS: medical_tier3_corroboration_regression (simulated via high-stakes source-shortage + tier3 flag checks)"
