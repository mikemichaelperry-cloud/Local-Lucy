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
printf '%s\n' "${MOCK_TRANSCRIPT:-Should I travel to Iran or Jordan at the moment?}"
SH
chmod +x "${FAKEBIN}/whisper-cli"

cat > "${TMPD}/mock_lucy_nl_chat.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
while IFS= read -r line; do
  [[ "${line}" == "/exit" ]] && break
done
echo "=== Local Lucy (Locked NL Chat) ==="
echo "From current sources:"
echo "Insufficient evidence from trusted sources."
echo "Sources:"
echo "- bbc.co.uk"
echo "- theguardian.com"
SH
chmod +x "${TMPD}/mock_lucy_nl_chat.sh"

OUT_FILE="${TMPD}/voice_sources.out"
ERR_FILE="${TMPD}/voice_sources.err"

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
  MOCK_TRANSCRIPT="Should I travel to Iran or Jordan at the moment?" \
  "${VOICE_SCRIPT}" >"${OUT_FILE}" 2>"${ERR_FILE}"

grep -q '^Answer:' "${OUT_FILE}" || die "missing Answer block"
grep -q '^From current sources:' "${OUT_FILE}" || die "missing evidence header"
grep -q '^Sources:' "${OUT_FILE}" || die "missing Sources block in voice output"
grep -q 'bbc.co.uk' "${OUT_FILE}" || die "missing source domain bbc.co.uk"
ok "voice output preserves Sources block for evidence answers"

echo "PASS: test_voice_evidence_sources_preserved"
