#!/usr/bin/env bash
# ROLE: HANDOFF / RESUME HELPER
# Secondary template-based handoff helper.
# Preferred handoff path: tools/write_local_lucy_handoff.sh
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${LUCY_ROOT:-$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)}"
DEV_NOTES_DIR="${ROOT}/dev_notes"
# V8 ISOLATION: No default frozen baseline from old versions
FROZEN_BASELINE_DEFAULT=""
FROZEN_BASELINE="${LUCY_FROZEN_BASELINE:-$FROZEN_BASELINE_DEFAULT}"

usage() {
  cat <<'USAGE'
Usage:
  new_session_handoff.sh [--title "Session title"] [--why "Why this session was needed"] [--open]

Creates a timestamped SESSION_HANDOFF note under dev_notes/ using the current standard format,
with full paths and reusable placeholders.
For current runtime-aware handoffs, prefer write_local_lucy_handoff.sh.

Options:
  --title TEXT   Handoff title suffix shown in the H1 line
  --why TEXT     Optional one-line reason for the session (prefills section 2)
  --open         Print file contents after creation
  -h, --help     Show this help
USAGE
}

TITLE_SUFFIX="Session Summary"
WHY_LINE=""
PRINT_FILE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --title)
      shift
      TITLE_SUFFIX="${1:-}"
      ;;
    --why)
      shift
      WHY_LINE="${1:-}"
      ;;
    --open)
      PRINT_FILE=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "ERR: unknown arg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift || true
done

mkdir -p "${DEV_NOTES_DIR}"

ts_file="$(date +'%Y-%m-%dT%H-%M-%S%z')"
date_human="$(date +'%B %d, %Y')"
time_human="$(date +'%H:%M:%S %z')"
outfile="${DEV_NOTES_DIR}/SESSION_HANDOFF_${ts_file}.md"

latest_handoff="$(
  ls -1 "${DEV_NOTES_DIR}"/SESSION_HANDOFF_*.md 2>/dev/null | sort | tail -1 || true
)"
if [[ -z "${latest_handoff}" ]]; then
  latest_handoff="(none found)"
fi

latest_report="$(
  ls -1 "${DEV_NOTES_DIR}"/CHATGPT*_*.md 2>/dev/null | sort | tail -1 || true
)"
if [[ -z "${latest_report}" ]]; then
  latest_report="(none this session yet)"
fi

why_block="${WHY_LINE:-[Fill in: user request / bug / regression / objective for this session.]}"

cat > "${outfile}" <<EOF
# Local Lucy Opt Session Handoff (${TITLE_SUFFIX})
Date: ${date_human}
Time: ${time_human}

- Project root: \`${ROOT}\`
- Snapshot (Opt primary dev line): \`${ROOT}\`
- Frozen baseline (immutable): \`${FROZEN_BASELINE}\`
- Previous handoff used: \`${latest_handoff}\`

## 0. Quick Resume
- Current task focus: [Fill in one line.]
- Current bottleneck: [Fill in one line.]
- Reusable baseline status: REUSABLE / STALE / INVALID
- Reuse-by-default rule:
  - [State what the next session should trust without rerunning.]
- Rerun triggers:
  - [List exact conditions that require fresh benchmark/tests.]
- First commands to run:
  - [Command #1]
  - [Command #2]
- Do not rerun by default:
  - [Broad battery / benchmark / report reloads that are unnecessary at session start.]

## 1. Final Health Status
Latest verified status in this session:
- [Fill in key result #1]: PASS/FAIL
- [Fill in key result #2]: PASS/FAIL
- [Fill in key result #3]: PASS/FAIL

Result:
- [2-4 concise bullets describing end-state and what is now true.]

## 2. Why This Session Was Needed
${why_block}

## 3. Continuity From This Session (What Happened, In Order)
1. Loaded latest continuity docs and established starting context.
2. Inspected relevant code paths / tests / runtime behavior.
3. Implemented targeted changes.
4. Added or updated regressions.
5. Ran validation and fixed any regressions introduced during implementation.
6. Produced documentation artifacts (if any) and created this handoff.

## 4. Key Changes Applied In This Session (with Intent)
### 4.1 [Change area]
File:
- \`/full/path/to/file\`

Changes:
- [What changed]

Intent:
- [Why this change exists]

### 4.2 [Change area]
File:
- \`/full/path/to/file\`

Changes:
- [What changed]

Intent:
- [Why this change exists]

## 5. Deviations From Expected Results (and How They Were Handled)
### 5.1 [Deviation title] (if any)
Observed deviation:
- [What failed / differed]

Root cause:
- [Cause]

Resolution:
- [Fix]

Status:
- Fixed in session / Deferred (with reason)

## 6. Tests / Checks Run In This Session (All PASS unless noted)
### 6.1 Syntax / parse checks
- [commands]

### 6.2 Targeted regressions
- [full paths to tests]

### 6.3 Existing regressions / smoke checks re-run
- [full paths to tests]

### 6.4 Validation inheritance note
- Validated fresh this session:
  - [List fresh measurements/tests.]
- Reused from earlier valid artifact:
  - [List reusable metrics/tests and artifact path.]
- Invalid results to ignore:
  - [List any stale/invalid artifact paths and why.]

## 7. Key Artifacts Produced / Updated In This Session
### 7.1 Primary report(s) / notes
File:
- \`${latest_report}\`

Intent:
- [What this artifact is for]

### 7.2 This continuity handoff note (this file)
File:
- \`${outfile}\`

Intent:
- Preserve handoff chain continuity and exact next-session starting point.

## 8. Known Residual Risk / Notes
- [Residual risk #1]
- [Residual risk #2]
- Baseline reuse note:
  - [State whether the next session should reuse or refresh current measurements.]
- Stabilization rule reminder:
  - \`No new features; one bug -> one patch -> one regression -> rerun battery.\`
- Next-session continuation rule:
  - Resume from the first failing test in the log, not from memory or mood.
- First failing test in latest log (if any):
  - \`[fill in exact test path + failure summary]\`

## 9. Recommended Next Steps (Optional)
1. Start from the first failing test in the latest regression log.
2. Apply one bugfix patch only.
3. Add/update exactly one regression for that bug.
4. Rerun the targeted battery before broad regressions.

## 10. Final Verification Block
- \`ACTIVE_ROOT=${ROOT}\`
- \`FROZEN_ROOTS=${FROZEN_BASELINE}\`
- \`EDITED_PATHS=[fill in semicolon-separated absolute paths]\`
- \`TEST_SUMMARY=[fill in concise pass/fail summary]\`
- \`BASELINE_DELTA=[fill in before/after or inherited baseline note]\`
- \`BASELINE_STATUS=[REUSABLE/STALE/INVALID]\`
- \`RERUN_TRIGGERS=[fill in exact rerun conditions]\`
- \`LAUNCHER_MAP_VERIFIED=[YES/NO]\`
- \`DESKTOP_REPORT_PATH=[fill in latest primary Desktop report path]\`
- \`HANDOFF_PATH=${outfile}\`
- \`OPEN_GAPS=[fill in concise remaining gaps]\`

EOF

echo "OK: created handoff template: ${outfile}"

if [[ "${PRINT_FILE}" == "1" ]]; then
  echo
  cat "${outfile}"
fi
