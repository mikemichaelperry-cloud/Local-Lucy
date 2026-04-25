#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${LUCY_ROOT:-$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)}"
CLASSIFIER="${ROOT}/tools/router/classify_intent.py"

needx(){ [[ -x "$1" ]] || { echo "ERR: missing executable: $1" >&2; exit 2; }; }
needx "$CLASSIFIER"

field(){
  local q="$1" key="$2"
  local plan
  plan="$($CLASSIFIER "$q")"
  PLAN_JSON="$plan" python3 - "$key" <<'PY'
import json, os, sys
k = sys.argv[1]
p = json.loads(os.environ["PLAN_JSON"])
v = p.get(k)
if isinstance(v, bool):
    print("true" if v else "false")
elif v is None:
    print("")
else:
    print(str(v))
PY
}

check_eq(){
  local q="$1" key="$2" want="$3"
  local got
  got="$(field "$q" "$key")"
  [[ "$got" == "$want" ]] || { echo "ERR: $q -> $key=$got expected=$want" >&2; exit 3; }
}

check_ne(){
  local q="$1" key="$2" bad="$3"
  local got
  got="$(field "$q" "$key")"
  [[ "$got" != "$bad" ]] || { echo "ERR: $q -> $key unexpectedly $got" >&2; exit 4; }
}

# Positive: must be conversation mode plan.
for q in \
  "What do you think about remote work?" \
  "Help me decide between staying and leaving" \
  "Why do people ghost friends?" \
  "How should I handle conflict at work?" \
  "Should I invest?"
do
  check_eq "$q" "output_mode" "CONVERSATION"
  check_eq "$q" "needs_web" "false"
  check_eq "$q" "allow_domains_file" ""
done

check_eq "Not necessary." "output_mode" "CONVERSATION"
check_eq "Not necessary." "needs_web" "false"

# Negative: must not become conversation mode.
check_ne "What is the latest world news?" "output_mode" "CONVERSATION"
check_ne "Is tadalafil safe with grapefruit?" "output_mode" "CONVERSATION"
check_ne "GDP of Italy 1970s" "output_mode" "CONVERSATION"
check_ne "Find me a source for inflation data" "output_mode" "CONVERSATION"
check_ne "Should I invest? Give me data and cite sources." "output_mode" "CONVERSATION"

echo "PASS: conversation_mode_classification"
