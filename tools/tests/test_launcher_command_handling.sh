#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"
LAUNCHER="${ROOT}/tools/start_local_lucy_opt_experimental_v7_dev.sh"

ok(){ echo "OK: $*"; }
die(){ echo "FAIL: $*" >&2; exit 1; }

[[ -x "${LAUNCHER}" ]] || die "missing executable: ${LAUNCHER}"

TMPD="$(mktemp -d)"
trap 'rm -rf "${TMPD}"' EXIT

MOCK_ROOT="${TMPD}/mock_root"
mkdir -p "${MOCK_ROOT}/tools" "${MOCK_ROOT}/tmp" "${MOCK_ROOT}/state"
LOG_FILE="${TMPD}/chat_calls.log"
PROMPT_FILE="${TMPD}/preprocess_prompt.txt"

cat > "${MOCK_ROOT}/lucy_chat.sh" <<'SH2'
#!/usr/bin/env bash
set -euo pipefail
printf '%s|aug_direct=%s|aug_policy=%s\n' "${1:-}" "${LUCY_AUGMENTED_DIRECT_REQUEST:-0}" "${LUCY_AUGMENTATION_POLICY:-disabled}" >> "${LUCY_TEST_LOG_FILE}"
printf '%s|aug_provider=%s\n' "${1:-}" "${LUCY_AUGMENTED_PROVIDER:-wikipedia}" >> "${LUCY_TEST_LOG_FILE}"
printf 'ok\n'
SH2
chmod +x "${MOCK_ROOT}/lucy_chat.sh"

for i in $(seq 1 21); do
  printf 'Prompt line %02d\n' "${i}" >> "${PROMPT_FILE}"
done

out="$({
  printf '/ststus\n'
  printf '/conversation mode\n'
  printf '/conversation on\n'
  printf '/conversation mode\n'
  printf '/augmented direct_allowed\n'
  printf '/augmented provider wikipedia\n'
  printf '/augmented provider grok\n'
  printf '/augmented provider openai\n'
  printf '/augmented provider\n'
  printf '/augmented provider invalid\n'
  printf '/augmented provider\n'
  printf '/augmented mode\n'
  printf '/status\n'
  printf 'run augmented: tell me a joke\n'
  printf '/bogus\n'
  printf '/quit\n'
} | LUCY_RUNTIME_AUTHORITY_ROOT="${MOCK_ROOT}" LUCY_TEST_LOG_FILE="${LOG_FILE}" LUCY_CODEX_PREPROCESS_PROMPT_PATH="${PROMPT_FILE}" "${LAUNCHER}" 2>&1)"

printf '%s\n' "${out}" | grep -q '== Local Lucy opt-experimental-v7-dev (launcher v7) ==' || die "launcher banner identity mismatch"
printf '%s\n' "${out}" | grep -q '=== Preprocess from Codex Launcher ===' || die "preprocess banner missing"
printf '%s\n' "${out}" | grep -q 'Prompt line 20' || die "preprocess prompt not shown"
if printf '%s\n' "${out}" | grep -q 'Prompt line 21'; then
  die "preprocess prompt should be truncated after 20 lines"
fi
printf '%s\n' "${out}" | grep -q '\[truncated to first 20 lines\]' || die "preprocess truncation note missing"
printf '%s\n' "${out}" | grep -q 'Mode: auto (router decides local/news/evidence)' || die "/ststus alias did not show status"
printf '%s\n' "${out}" | grep -q 'Conversation mode override: OFF' || die "conversation mode status (off) missing"
printf '%s\n' "${out}" | grep -q 'Conversation mode override: ON' || die "conversation mode status (on) missing"
printf '%s\n' "${out}" | grep -q 'Augmented policy: direct_allowed' || die "augmented policy status missing"
printf '%s\n' "${out}" | grep -q 'Selected augmented provider: wikipedia' || die "wikipedia provider set status missing"
printf '%s\n' "${out}" | grep -q 'Selected augmented provider: grok' || die "grok provider set status missing"
printf '%s\n' "${out}" | grep -q 'Selected augmented provider: openai' || die "augmented provider status missing"
printf '%s\n' "${out}" | grep -q 'ERROR: invalid augmented provider: invalid' || die "invalid augmented provider error missing"
openai_count="$(printf '%s\n' "${out}" | grep -c 'Selected augmented provider: openai' || true)"
[[ "${openai_count}" -ge 2 ]] || die "invalid provider should not change provider state"
printf '%s\n' "${out}" | grep -q 'Unknown command: /bogus' || die "unknown slash command guard missing"
printf '%s\n' "${out}" | grep -q 'Augmented policy: direct_allowed' || die "/status augmented policy missing"
printf '%s\n' "${out}" | grep -q 'Selected augmented provider: openai' || die "/status augmented provider missing"

[[ -s "${LOG_FILE}" ]] || die "expected run augmented query to be forwarded"
grep -q 'tell me a joke|aug_direct=1|aug_policy=direct_allowed' "${LOG_FILE}" || die "run augmented should forward direct request marker and policy"
grep -q 'tell me a joke|aug_provider=openai' "${LOG_FILE}" || die "run augmented should forward selected augmented provider"

ok "launcher handles /ststus alias, /conversation mode, and blocks unknown slash commands"
echo "PASS: launcher_command_handling"
