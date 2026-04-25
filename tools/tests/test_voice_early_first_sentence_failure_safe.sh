#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"
VOICE_TOOL="${ROOT}/tools/lucy_voice_ptt.sh"

ok(){ echo "OK: $*"; }
die(){ echo "FAIL: $*" >&2; exit 1; }

[[ -f "${VOICE_TOOL}" ]] || die "missing voice tool: ${VOICE_TOOL}"

TMPD="$(mktemp -d)"
trap 'rm -rf "${TMPD}"' EXIT

source /dev/stdin <<<"$(awk '
  /FIRST_SENTENCE_EARLY_STARTED=0/ {capture=1}
  capture && /^pick_recorder$/ {exit}
  capture {print}
' "${VOICE_TOOL}")"

TTS_ENGINE="stub"
TTS_CHUNK_PAUSE_MS=0

run_success_case(){
  local log_file="${TMPD}/success.log"
  : > "${log_file}"

  speak_answer_once(){
    printf '%s\n' "$1" >> "${log_file}"
    return 0
  }

  prepare_first_sentence_tts_state
  ( exit 0 ) &
  FIRST_SENTENCE_TTS_PID="$!"
  FIRST_SENTENCE_EARLY_STARTED=1

  speak_answer "First sentence. Second sentence."

  mapfile -t spoken_lines < "${log_file}"
  [[ "${#spoken_lines[@]}" -eq 1 ]] || die "expected one spoken chunk after successful early TTS, got ${#spoken_lines[@]}"
  [[ "${spoken_lines[0]}" == "Second sentence." ]] || die "expected first chunk to be skipped after successful early TTS, got: ${spoken_lines[0]}"
  ok "successful early first-sentence playback skips duplicate first chunk"
}

run_failure_case(){
  local log_file="${TMPD}/failure.log"
  : > "${log_file}"

  speak_answer_once(){
    printf '%s\n' "$1" >> "${log_file}"
    return 0
  }

  prepare_first_sentence_tts_state
  ( exit 1 ) &
  FIRST_SENTENCE_TTS_PID="$!"
  FIRST_SENTENCE_EARLY_STARTED=1

  speak_answer "First sentence. Second sentence."

  mapfile -t spoken_lines < "${log_file}"
  [[ "${#spoken_lines[@]}" -eq 2 ]] || die "expected both chunks after failed early TTS, got ${#spoken_lines[@]}"
  [[ "${spoken_lines[0]}" == "First sentence." ]] || die "expected failed early TTS to preserve first chunk playback, got: ${spoken_lines[0]}"
  [[ "${spoken_lines[1]}" == "Second sentence." ]] || die "expected second chunk after failed early TTS, got: ${spoken_lines[1]}"
  ok "failed early first-sentence playback falls back to full answer speech"
}

run_chunk_alignment_case(){
  local captured=""

  start_first_sentence_tts(){
    captured="$1"
    FIRST_SENTENCE_TTS_TEXT="$1"
    FIRST_SENTENCE_TTS_PID=""
    FIRST_SENTENCE_EARLY_STARTED=1
  }

  prepare_first_sentence_tts_state
  maybe_start_first_sentence_tts $'Headline one...\nHeadline two...'

  [[ "${captured}" == "Headline one..." ]] || die "expected early TTS to use the first split chunk, got: ${captured}"
  ok "early first-sentence playback uses split_tts_chunks basis"
}

run_abort_cleanup_case(){
  prepare_first_sentence_tts_state
  ( sleep 30 ) &
  FIRST_SENTENCE_TTS_PID="$!"
  FIRST_SENTENCE_EARLY_STARTED=1
  FIRST_SENTENCE_TTS_TEXT="Pending sentence."

  abort_first_sentence_tts

  if kill -0 "${FIRST_SENTENCE_TTS_PID}" >/dev/null 2>&1; then
    die "expected abort_first_sentence_tts to terminate the early playback child"
  fi
  [[ "${FIRST_SENTENCE_EARLY_STARTED}" == "0" ]] || die "expected early-start flag reset after abort"
  [[ -z "${FIRST_SENTENCE_TTS_PID}" ]] || die "expected early playback pid cleared after abort"
  [[ -z "${FIRST_SENTENCE_TTS_TEXT}" ]] || die "expected early playback text cleared after abort"
  ok "abort_first_sentence_tts cleans up the early playback child and state"
}

run_success_case
run_failure_case
run_chunk_alignment_case
run_abort_cleanup_case

echo "PASS: test_voice_early_first_sentence_failure_safe"
