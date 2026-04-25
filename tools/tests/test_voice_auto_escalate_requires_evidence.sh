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
printf '%s\n' "${MOCK_TRANSCRIPT:-Can I feed my dog tuna?}"
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
printf '%s\n' "${first}" >> "${VOICE_ROUTED_CAPTURE_FILE}"
if [[ "${first}" == evidence:* ]]; then
  cat <<'OUT'
=== Local Lucy (Locked NL Chat) ===
Answer:
From current sources:
Answer-ready evidence output.
Sources:
- bbc.co.uk
OUT
else
  cat <<OUT
=== Local Lucy (Locked NL Chat) ===
Answer:
This requires evidence mode.
Run: run online: ${first}
OUT
fi
EOS
chmod +x "${TMPD}/mock_lucy_nl_chat.sh"

out_file="${TMPD}/voice.out"
routed_file="${TMPD}/voice.routed"

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
  MOCK_TRANSCRIPT="Can I feed my dog tuna?" \
  VOICE_ROUTED_CAPTURE_FILE="${routed_file}" \
  "${VOICE_SCRIPT}" >"${out_file}" 2>/dev/null

[[ -s "${routed_file}" ]] || die "missing routed capture"
count="$(wc -l < "${routed_file}" | tr -d ' ')"
[[ "${count}" == "2" ]] || die "expected 2 routed calls (local + evidence), got ${count}"
first="$(sed -n '1p' "${routed_file}")"
second="$(sed -n '2p' "${routed_file}")"
[[ "${first}" != evidence:* ]] || die "first route unexpectedly evidence-prefixed: ${first}"
[[ "${second}" == evidence:* ]] || die "second route missing evidence prefix: ${second}"

grep -Fq "Answer-ready evidence output." "${out_file}" || die "missing escalated evidence answer"
if grep -Fq "Run: run online:" "${out_file}"; then
  die "voice output still leaked manual rerun instruction"
fi

ok "voice auto-escalates requires-evidence replies in online mode"
echo "PASS: test_voice_auto_escalate_requires_evidence"
