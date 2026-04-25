#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${LUCY_ROOT:-$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)}"
SHIM="${ROOT}/tools/conversation/conversation_cadence_shim.py"

needx(){ [[ -x "$1" ]] || { echo "ERR: missing executable: $1" >&2; exit 2; }; }
needx "$SHIM"

# 1) Opening + closing boilerplate removal.
out1="$(printf '%s\n' "Sure! You can start with a short list of priorities." "Hope that helps." | LUCY_USER_PROMPT="I need advice on prioritization for next quarter with deadlines and tradeoffs" python3 "$SHIM")"
printf '%s\n' "$out1" | grep -qi '^sure' && { echo "ERR: opener was not removed" >&2; exit 3; }
printf '%s\n' "$out1" | grep -qi 'hope that helps' && { echo "ERR: closer was not removed" >&2; exit 3; }
printf '%s\n' "$out1" | grep -q 'You can start with a short list of priorities\.' || { echo "ERR: core answer missing after cleanup" >&2; exit 3; }

# 1b) Platform boilerplate opener removal.
out1b="$(printf '%s\n' "I'm here to provide information and support within my operating envelope. What would you like to discuss or ask about?" | LUCY_USER_PROMPT="Hi Lucy, how are you?" python3 "$SHIM")"
printf '%s\n' "$out1b" | grep -qi "i'm here to provide information and support" && { echo "ERR: platform opener was not removed" >&2; exit 3; }
printf '%s\n' "$out1b" | grep -qi 'Example: when priorities are vague' && { echo "ERR: greeting should not inject generic example" >&2; exit 3; }
printf '%s\n' "$out1b" | grep -qi 'Bottom line: choose one clear action' && { echo "ERR: greeting should not inject generic bottom line" >&2; exit 3; }

# 1c) Non-coaching conversation should avoid generic coaching injection.
out1c="$(printf '%s\n' "Good morning! Considering sentience in AI is a complex topic." | LUCY_USER_PROMPT="How would you gauge whether an AI is sentient?" LUCY_CONV_INTENT=LOCAL_KNOWLEDGE python3 "$SHIM")"
printf '%s\n' "$out1c" | grep -qi 'Example: when priorities are vague' && { echo "ERR: philosophy prompt should not inject generic example" >&2; exit 3; }
printf '%s\n' "$out1c" | grep -qi 'Bottom line: choose one clear action' && { echo "ERR: philosophy prompt should not inject generic bottom line" >&2; exit 3; }

# 2) Length cap for longer user prompts.
long_raw="First sentence is compact. Second sentence is intentionally very long so the deterministic truncation path is exercised and trimmed cleanly without adding any ellipsis marker."
out2="$(printf '%s' "$long_raw" | LUCY_USER_PROMPT="Please give me a concise but practical answer about balancing work and personal tasks this week" LUCY_CONV_MAX_CHARS_MED=80 python3 "$SHIM")"
chars2="$(printf '%s' "$out2" | wc -c | tr -d ' ')"
[[ "$chars2" -le 80 ]] || { echo "ERR: length cap not applied (${chars2} > 80)" >&2; exit 4; }
printf '%s\n' "$out2" | grep -q '\.\.\.' && { echo "ERR: ellipsis found; truncation must be clean" >&2; exit 4; }

# 3) Bullet collapse for short prompts (<=12 words).
out3="$(cat <<'EOF' | LUCY_USER_PROMPT="Help me decide" python3 "$SHIM"
- Compare commute time
- Compare salary stability
- Compare team growth
EOF
)"
printf '%s\n' "$out3" | grep -q '^-' && { echo "ERR: bullets should collapse for short prompts" >&2; exit 5; }
printf '%s\n' "$out3" | grep -q 'Compare commute time' || { echo "ERR: collapsed paragraph missing content" >&2; exit 5; }
printf '%s\n' "$out3" | grep -q 'Compare salary stability' || { echo "ERR: collapsed paragraph missing content" >&2; exit 5; }

# 4) Already-substantive clean text should stay unchanged.
clean_in="Use a smaller pan and reduce heat for even browning. Example: if the pan smokes in under 30 seconds, lower heat and wait 1 minute. Bottom line: steady heat gives even color."
out4="$(printf '%s' "$clean_in" | LUCY_USER_PROMPT="How do I cook roast beef evenly in a pan with limited equipment" python3 "$SHIM")"
[[ "$out4" == "$clean_in" ]] || { echo "ERR: clean text changed unexpectedly" >&2; exit 6; }

# 5) Dismissal prompts should suppress follow-up output.
out5="$(printf '%s' "I'm here to help with any questions or topics you'd like to discuss. What's on your mind?" | LUCY_USER_PROMPT="Not necessary." python3 "$SHIM")"
[[ -z "$out5" ]] || { echo "ERR: dismissal prompt should emit empty output" >&2; exit 7; }

echo "PASS: conversation_cadence_shim"
