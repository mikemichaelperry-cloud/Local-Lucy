#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"
VOICE_SCRIPT="${ROOT}/tools/lucy_voice_ptt.sh"

ok(){ echo "OK: $*"; }
die(){ echo "FAIL: $*" >&2; exit 1; }

[[ -x "${VOICE_SCRIPT}" ]] || die "missing executable: ${VOICE_SCRIPT}"

TMPD="$(mktemp -d)"
trap 'rm -rf "${TMPD}"' EXIT

FAKEBIN="${TMPD}/bin"
mkdir -p "${FAKEBIN}"

cat > "${FAKEBIN}/arecord" <<'EOS'
#!/usr/bin/env bash
set -euo pipefail
out="${@: -1}"
printf 'RIFFMOCKWAVE' > "${out}"
EOS
chmod +x "${FAKEBIN}/arecord"

cat > "${FAKEBIN}/whisper-cli" <<'EOS'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "${MOCK_TRANSCRIPT:-forward slash online}"
EOS
chmod +x "${FAKEBIN}/whisper-cli"

cat > "${TMPD}/mock_lucy_nl_chat.sh" <<'EOS'
#!/usr/bin/env bash
set -euo pipefail
first=""
while IFS= read -r line; do
  [[ -n "${first}" ]] || first="${line}"
  [[ "${line}" == "/exit" ]] && break
done
if [[ -n "${VOICE_ROUTED_CAPTURE_FILE:-}" ]]; then
  printf '%s\n' "${first}" >> "${VOICE_ROUTED_CAPTURE_FILE}"
fi
echo "=== Local Lucy (Locked NL Chat) ==="
echo "lucy> routed-ok"
echo "lucy> "
EOS
chmod +x "${TMPD}/mock_lucy_nl_chat.sh"

run_cmd_case(){
  local label="$1"
  local transcript="$2"
  local expected_line="$3"
  local out_file="${TMPD}/${label}.out"
  local routed_file="${TMPD}/${label}.routed"

  printf '\n' | \
    PATH="${FAKEBIN}:$PATH" \
    LUCY_ROOT="${ROOT}" \
    LUCY_VOICE_NL_CHAT_BIN="${TMPD}/mock_lucy_nl_chat.sh" \
    LUCY_VOICE_STT_ENGINE="whisper" \
    LUCY_VOICE_WHISPER_BIN="${FAKEBIN}/whisper-cli" \
    LUCY_VOICE_TTS_ENGINE="none" \
    LUCY_VOICE_PTT_MODE="enter" \
    LUCY_VOICE_ONESHOT="1" \
    LUCY_VOICE_ROUTE_MODE="auto" \
    MOCK_TRANSCRIPT="${transcript}" \
    VOICE_ROUTED_CAPTURE_FILE="${routed_file}" \
    "${VOICE_SCRIPT}" >"${out_file}" 2>/dev/null

  grep -Fq "${expected_line}" "${out_file}" || die "${label}: missing expected output '${expected_line}'"
  if [[ -s "${routed_file}" ]]; then
    die "${label}: expected no NL routing for command, got $(cat "${routed_file}")"
  fi
  ok "${label}"
}

run_cmd_case "spoken_mode_online" "forward slash online" "Mode: online"
run_cmd_case "spoken_mode_offline" "slash offline" "Mode: offline"
run_cmd_case "spoken_conversation_off" "conversation off" "Conversation mode: off"
run_cmd_case "spoken_memory_status" "memory status" "Memory:"

echo "PASS: test_voice_spoken_command_mapping"
