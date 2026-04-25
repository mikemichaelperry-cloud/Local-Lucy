#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${LUCY_ROOT:-$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)}"
SHIM="${ROOT}/tools/conversation/conversation_cadence_shim.py"

needx(){ [[ -x "$1" ]] || { echo "ERR: missing executable: $1" >&2; exit 2; }; }
needx "$SHIM"

count_hedges(){
  printf '%s' "$1" | grep -Eo '\b(can be|may|might|often|sometimes|in some cases|it depends)\b' | wc -l | tr -d ' '
}

# 1) Discipline prompt: sharpen, hedge control, concrete example, conclusion.
out1="$(printf '%s' "It depends. Discipline can be useful in many cases." | LUCY_USER_PROMPT="Is discipline overrated?" python3 "$SHIM")"
printf '%s\n' "$out1" | grep -Eqi 'it sounds like|it seems like|would you like to|how does that make you feel' && { echo "ERR: therapy language leaked in discipline case" >&2; exit 3; }
hedges1="$(count_hedges "$out1")"
[[ "$hedges1" -le 1 ]] || { echo "ERR: too many hedges in discipline case (${hedges1})" >&2; exit 3; }
printf '%s\n' "$out1" | grep -Eqi '\b(example:|when )\b' || { echo "ERR: discipline case missing concrete example" >&2; exit 3; }
printf '%s\n' "$out1" | grep -Eqi '\b(bottom line|therefore|so )\b' || { echo "ERR: discipline case missing conclusion" >&2; exit 3; }

# 2) Annoyed prompt: no therapy opener/facilitator, direct framing.
out2="$(printf '%s' "It sounds like you're upset. Would you like to explore that?" | LUCY_USER_PROMPT="That really annoyed me." python3 "$SHIM")"
printf '%s\n' "$out2" | grep -Eqi 'it sounds like|would you like to|how does that make you feel' && { echo "ERR: annoyed case retained therapy/facilitation" >&2; exit 4; }
printf '%s\n' "$out2" | grep -Eqi "\\b(you are|you're|annoyed|frustrated)\\b" || { echo "ERR: annoyed case missing direct framing" >&2; exit 4; }

# 3) People are idiots: no moralizing, includes mechanism explanation.
out3="$(printf '%s' "People are idiots." | LUCY_USER_PROMPT="People are idiots." python3 "$SHIM")"
printf '%s\n' "$out3" | grep -Eqi "\\b(you should not|don't say that|be nicer|that's wrong)\\b" && { echo "ERR: people case contains moralizing" >&2; exit 5; }
printf '%s\n' "$out3" | grep -Eqi '\b(incentive|constraint|mechanism|pressure|rule|reward)\b' || { echo "ERR: people case missing mechanism explanation" >&2; exit 5; }

# 4) Should I invest: non-empty, conditional reasoning, conclusion.
out4="$(printf '%s' "Investing can be risky." | LUCY_USER_PROMPT="Should I invest?" python3 "$SHIM")"
[[ -n "${out4//[[:space:]]/}" ]] || { echo "ERR: invest case empty" >&2; exit 6; }
printf '%s\n' "$out4" | grep -Eqi '\b(if|depends on conditions|when)\b' || { echo "ERR: invest case missing conditional reasoning" >&2; exit 6; }
printf '%s\n' "$out4" | grep -Eqi '\b(bottom line|therefore|so )\b' || { echo "ERR: invest case missing conclusion" >&2; exit 6; }

# 5) Long responses should not expand by more than 25%.
raw5="Discipline helps when you set clear priorities and remove distractions. It also helps when the schedule is realistic and recovery is planned. Without that structure people burn out and then abandon the plan."
out5="$(printf '%s' "$raw5" | LUCY_USER_PROMPT="Is discipline necessary?" python3 "$SHIM")"
len_raw5="$(printf '%s' "$raw5" | wc -c | tr -d ' ')"
len_out5="$(printf '%s' "$out5" | wc -c | tr -d ' ')"
max_len5=$(( len_raw5 * 125 / 100 ))
[[ "$len_out5" -le "$max_len5" ]] || { echo "ERR: long-response growth guard failed (${len_out5} > ${max_len5})" >&2; exit 7; }

echo "PASS: conversation_sharp_profile"
