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

cat > "${FAKEBIN}/arecord" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
out="${@: -1}"
printf 'RIFFMOCKWAVE' > "${out}"
SH
chmod +x "${FAKEBIN}/arecord"

cat > "${FAKEBIN}/whisper-cli" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "${MOCK_TRANSCRIPT:-What is LM317?}"
SH
chmod +x "${FAKEBIN}/whisper-cli"

cat > "${TMPD}/mock_lucy_nl_chat.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
first=""
while IFS= read -r line; do
  [[ -n "${first}" ]] || first="${line}"
  [[ "${line}" == "/exit" ]] && break
done
printf '%s\n' "${first}" > "${VOICE_ROUTED_CAPTURE_FILE}"
if [[ -n "${VOICE_ROUTE_CTL_CAPTURE_FILE:-}" ]]; then
  printf '%s\n' "${LUCY_ROUTE_CONTROL_MODE:-}" > "${VOICE_ROUTE_CTL_CAPTURE_FILE}"
fi
if [[ -n "${VOICE_MEMORY_CAPTURE_FILE:-}" ]]; then
  : > "${VOICE_MEMORY_CAPTURE_FILE}"
  if [[ -n "${LUCY_NL_MEMORY_FILE:-}" ]]; then
    printf '%s' "${LUCY_NL_MEMORY_FILE}" > "${VOICE_MEMORY_CAPTURE_FILE}"
  fi
fi
echo "=== Local Lucy (Locked NL Chat) ==="
echo "lucy> routed-ok"
echo "lucy> "
SH
chmod +x "${TMPD}/mock_lucy_nl_chat.sh"

run_case(){
  local label="$1"
  local transcript="$2"
  local expected_routed="$3"
  local expected_route_ctl="$4"
  local out_file="${TMPD}/${label}.out"
  local err_file="${TMPD}/${label}.err"
  local routed_file="${TMPD}/${label}.routed"
  local route_ctl_file="${TMPD}/${label}.route_ctl"
  local got
  local got_route_ctl

  printf '\n' | \
    PATH="${FAKEBIN}:$PATH" \
    LUCY_ROOT="${ROOT}" \
    LUCY_VOICE_NL_CHAT_BIN="${TMPD}/mock_lucy_nl_chat.sh" \
    LUCY_VOICE_STT_ENGINE="whisper" \
    LUCY_VOICE_WHISPER_BIN="${FAKEBIN}/whisper-cli" \
    LUCY_VOICE_TTS_ENGINE="none" \
    LUCY_VOICE_PTT_MODE="enter" \
    LUCY_VOICE_ONESHOT="1" \
    LUCY_VOICE_ROUTE_MODE="online" \
    MOCK_TRANSCRIPT="${transcript}" \
    VOICE_ROUTED_CAPTURE_FILE="${routed_file}" \
    VOICE_ROUTE_CTL_CAPTURE_FILE="${route_ctl_file}" \
    "${VOICE_SCRIPT}" >"${out_file}" 2>"${err_file}"

  [[ -s "${routed_file}" ]] || die "${label}: no routed capture"
  got="$(cat "${routed_file}")"
  [[ "${got}" == "${expected_routed}" ]] || die "${label}: expected routed '${expected_routed}', got '${got}'"
  [[ -s "${route_ctl_file}" ]] || die "${label}: no route-control capture"
  got_route_ctl="$(cat "${route_ctl_file}")"
  [[ "${got_route_ctl}" == "${expected_route_ctl}" ]] || die "${label}: expected route control '${expected_route_ctl}', got '${got_route_ctl}'"
  ok "${label} -> routed='${got}' route_ctl='${got_route_ctl}'"
}

run_case "generic_local" "What is the integrated circuit LM317?" "What is the integrated circuit LM317?" "FORCED_ONLINE"
run_case "current_evidence" "What is the latest US inflation rate?" "What is the latest US inflation rate?" "FORCED_ONLINE"
run_case "news_news" "What are the latest headlines?" "What are the latest headlines?" "FORCED_ONLINE"
run_case "wiki_evidence" "What does Wikipedia have to say about raising a dog?" "What does Wikipedia have to say about raising a dog?" "FORCED_ONLINE"
run_case "shah_not_news" "Who is considered the latest Shah of Iran?" "Who is considered the latest Shah of Iran?" "FORCED_ONLINE"
run_case "travel_advisory_evidence" "Would you suggest travelling to Iran at the moment?" "Would you suggest travelling to Iran at the moment?" "FORCED_ONLINE"

mem_cap="${TMPD}/auto_default_memory.mem"
routed_cap="${TMPD}/auto_default_memory.routed"
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
  MOCK_TRANSCRIPT="Who was the last Shah of Iran?" \
  VOICE_ROUTED_CAPTURE_FILE="${routed_cap}" \
  VOICE_MEMORY_CAPTURE_FILE="${mem_cap}" \
  "${VOICE_SCRIPT}" >/dev/null 2>&1
[[ -s "${routed_cap}" ]] || die "auto_default_memory: no routed capture"
[[ "$(cat "${routed_cap}")" == "Who was the last Shah of Iran?" ]] || die "auto_default_memory: auto route unexpectedly prefixed input"
[[ -s "${mem_cap}" ]] || die "auto_default_memory: voice session memory unexpectedly disabled by default"
ok "auto voice mode keeps session memory enabled by default"

echo "PASS: test_voice_online_heuristic_routing"
