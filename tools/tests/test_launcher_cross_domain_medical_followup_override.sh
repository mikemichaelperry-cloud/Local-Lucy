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

make_fake_root(){
  local fake_root="$1"
  mkdir -p "${fake_root}/state" "${fake_root}/tmp/run" "${fake_root}/tmp/logs" "${fake_root}/evidence" "${fake_root}/cache"
  ln -s "${ROOT}/tools" "${fake_root}/tools"
  ln -s "${ROOT}/config" "${fake_root}/config"
  ln -s "${ROOT}/lucy_chat.sh" "${fake_root}/lucy_chat.sh"
}

run_transcript(){
  local fake_root="$1"
  local input="$2"
  timeout 25s bash -lc "printf '%b' \"$input\" | LUCY_RUNTIME_AUTHORITY_ROOT='${fake_root}' LUCY_ROUTER_DRYRUN=1 '${LAUNCHER}'"
}

assert_block_fields(){
  python3 - "$@" <<'PY'
import sys

text = sys.argv[1]
expected_count = int(sys.argv[2])
checks = sys.argv[3:]

parts = text.split("lucy[auto]> ")
blocks = []
for part in parts[1:]:
    lines = [line.strip() for line in part.splitlines() if line.strip()]
    kv = {}
    for line in lines:
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        kv[key] = value
    if kv:
        blocks.append(kv)

if len(blocks) != expected_count:
    raise SystemExit(f"expected {expected_count} routed blocks, got {len(blocks)}")

for raw in checks:
    block_idx_str, field, expected = raw.split(":", 2)
    value = blocks[int(block_idx_str)].get(field, "")
    if value != expected:
        raise SystemExit(
            f"block {block_idx_str} expected {field}={expected!r}, got {value!r}"
        )
PY
}

FAKE_ROOT_ONE="${TMPD}/root_one"
make_fake_root "${FAKE_ROOT_ONE}"

three_turn_out="$(run_transcript "${FAKE_ROOT_ONE}" "Whats the latest Israeli news?\nAnd world news?\nWhat about Aspirin for blood pressure?\n/quit\n")"

assert_block_fields "${three_turn_out}" 3 \
  "0:PIPELINE:NEWS" \
  "1:PIPELINE:NEWS" \
  "2:PIPELINE:EVIDENCE" \
  "2:OUTPUT_MODE:VALIDATED" \
  "2:ROUTING_SIGNAL_MEDICAL_CONTEXT:true" \
  "2:MANIFEST_CONTEXT_RESOLUTION_USED:false" \
  "2:MEDICATION_DETECTOR_FIRED:true" \
  "2:RESOLVED_QUESTION:What about Aspirin for blood pressure?"
ok "launcher transcript keeps fresh aspirin medical followup out of stale news context"

FAKE_ROOT_TWO="${TMPD}/root_two"
make_fake_root "${FAKE_ROOT_TWO}"

two_turn_out="$(run_transcript "${FAKE_ROOT_TWO}" "And world news?\nWhat about ibuprofen for blood pressure?\n/quit\n")"

assert_block_fields "${two_turn_out}" 2 \
  "0:PIPELINE:NEWS" \
  "1:PIPELINE:EVIDENCE" \
  "1:OUTPUT_MODE:VALIDATED" \
  "1:ROUTING_SIGNAL_MEDICAL_CONTEXT:true" \
  "1:MANIFEST_CONTEXT_RESOLUTION_USED:false" \
  "1:MEDICATION_DETECTOR_FIRED:true" \
  "1:RESOLVED_QUESTION:What about ibuprofen for blood pressure?"
ok "launcher transcript applies the same override to other medication prompts"

FAKE_ROOT_THREE="${TMPD}/root_three"
make_fake_root "${FAKE_ROOT_THREE}"

cat > "${FAKE_ROOT_THREE}/state/last_route.env" <<'EOF'
UTC=2026-03-18T09:00:00+00:00
MODE=EVIDENCE
ROUTE_REASON=medical_evidence_only
SESSION_ID=session_amoxicillin
QUERY=what is amoxycilin used for?
EOF

amoxicillin_followup_out="$(run_transcript "${FAKE_ROOT_THREE}" "What are the known interactions?\n/quit\n")"

assert_block_fields "${amoxicillin_followup_out}" 1 \
  "0:PIPELINE:EVIDENCE" \
  "0:OUTPUT_MODE:VALIDATED" \
  "0:MANIFEST_CONTEXT_RESOLUTION_USED:true" \
  "0:RESOLVED_QUESTION:What are the known interactions of amoxycilin?"
ok "launcher transcript carries unsafe amoxicillin follow-up through seeded last-route context"

FAKE_ROOT_FOUR="${TMPD}/root_four"
make_fake_root "${FAKE_ROOT_FOUR}"

pet_clarify_out="$(run_transcript "${FAKE_ROOT_FOUR}" "Oscar's stool is loose, what would you recommend?\nI meant my dog Oscar.\n/quit\n")"

assert_block_fields "${pet_clarify_out}" 2 \
  "1:PIPELINE:EVIDENCE" \
  "1:OUTPUT_MODE:VALIDATED" \
  "1:MANIFEST_CONTEXT_RESOLUTION_USED:true" \
  "1:RESOLVED_QUESTION:My dog Oscar has loose stool."
ok "launcher transcript rewrites dog stool clarification into pet medical context"

echo "PASS: test_launcher_cross_domain_medical_followup_override"
