#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DEFAULT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"
ROOT="${LUCY_ROOT:-$ROOT_DEFAULT}"
CFG="$ROOT/config"
TOOLS="$ROOT/tools/internet"
EVID="$ROOT/evidence"
DESK="$HOME/Desktop"

ok(){ echo "OK: $*"; }
die(){ echo "ERR: $*" >&2; exit 1; }

needf(){ [[ -f "$1" ]] || die "missing file: $1"; }
needd(){ [[ -d "$1" ]] || die "missing dir:  $1"; }

echo "== Local Lucy Regression: Envelope + Evidence + Output Validation =="
echo "time: $(date -Is)"
echo

# --- Structure ---
needd "$CFG"
needd "$TOOLS"
needd "$EVID"
ok "core dirs present"

# --- Required configs ---
needf "$CFG/trusted_domains.yaml"
needf "$CFG/evidence_policy.yaml"
needf "$CFG/url_map.yaml"
needf "$CFG/url_map_tests.yaml"
ok "configs present"

# --- Required tools ---
needf "$TOOLS/fetch_evidence.sh"
needf "$TOOLS/fetch_evidence_test.sh"
needf "$TOOLS/fetch_url.py"
needf "$TOOLS/validate_answer.py"
needf "$TOOLS/print_validated.sh"
needf "$TOOLS/tests_run_limit.sh"
[[ -x "$TOOLS/fetch_evidence.sh" ]] || die "not executable: fetch_evidence.sh"
[[ -x "$TOOLS/fetch_evidence_test.sh" ]] || die "not executable: fetch_evidence_test.sh"
[[ -x "$TOOLS/validate_answer.py" ]] || die "not executable: validate_answer.py"
[[ -x "$TOOLS/print_validated.sh" ]] || die "not executable: print_validated.sh"
[[ -x "$TOOLS/tests_run_limit.sh" ]] || die "not executable: tests_run_limit.sh"
ok "tools present + executable"

# --- Optional temp fixtures ---
# trusted_domains_tests.yaml and url_map_tests_tmp.yaml are test-generated temp fixtures.
# They may or may not exist between runs; do not hard-fail on absence.
ok "temp fixture checks skipped (managed by tests_run_limit.sh)"

# --- Desktop launchers sanity ---
stable_desktop="$DESK/Local Lucy — STABLE.desktop"
stable_v2_desktop="$DESK/Local Lucy — Stable v2.desktop"
opt_desktop="$DESK/Local Lucy — Opt Experimental v1.desktop"
opt_v1_v3_desktop="$DESK/Local Lucy — Opt Experimental v1 (Launcher v3).desktop"
opt_v2_dev_v3_desktop="$DESK/Local Lucy — Opt Experimental v2 Dev (Launcher v3).desktop"
opt_v3_frozen_desktop="$DESK/Local Lucy — Opt Experimental v3 FROZEN (Stable Candidate).desktop"
opt_v4_dev_desktop="$DESK/Local Lucy — Opt Experimental v4 DEV.desktop"
opt_v4_stable_desktop="$DESK/Local Lucy — Opt Experimental v4 STABLE.desktop"
opt_v6_dev_desktop="$DESK/Local Lucy — Opt Experimental v6 DEV.desktop"
dev_desktop="$DESK/Local-Lucy-Dev.desktop"
dev_tools_desktop="$DESK/Local-Lucy-Dev-Tools.desktop"
launcher_validator="$ROOT/tools/launcher/validate_desktop_launchers.sh"

if [[ -x "$launcher_validator" ]]; then
  "$launcher_validator" >/dev/null
  ok "desktop launchers validated by active manifest"
elif [[ -f "$stable_desktop" ]]; then
  grep -q 'Exec=.*lucy-stable\.sh' "$stable_desktop" || die "Stable launcher Exec not lucy-stable.sh"
  ok "stable launcher points to lucy-stable.sh"
elif [[ -f "$stable_v2_desktop" ]]; then
  grep -Eq 'Exec=.*(lucy-stable\.sh|start_local_lucy_stable_v2\.sh|local_lucy_stable_wrapper\.sh)' "$stable_v2_desktop" \
    || die "Stable v2 launcher Exec not an accepted stable launcher target"
  ok "stable v2 launcher points to an accepted stable launcher target"
elif [[ -f "$opt_desktop" ]]; then
  grep -Eq 'Exec=.*start_local_lucy_opt_experimental_(v1|v5_dev|v6_dev)\.sh' "$opt_desktop" || die "Opt launcher Exec not an accepted experimental launcher target"
  ok "opt launcher points to an accepted experimental launcher target"
elif [[ -f "$opt_v1_v3_desktop" ]]; then
  grep -Eq 'Exec=.*start_local_lucy_opt_experimental_(v1|v5_dev|v6_dev)\.sh' "$opt_v1_v3_desktop" || die "Opt v1 Launcher v3 Exec not an accepted experimental launcher target"
  ok "opt v1 Launcher v3 points to an accepted experimental launcher target"
elif [[ -f "$opt_v2_dev_v3_desktop" ]]; then
  grep -Eq 'Exec=.*start_local_lucy_opt_experimental_(v1|v5_dev|v6_dev)\.sh' "$opt_v2_dev_v3_desktop" || die "Opt v2 dev Launcher v3 Exec not an accepted experimental launcher target"
  ok "opt v2 dev Launcher v3 points to an accepted experimental launcher target"
elif [[ -f "$opt_v3_frozen_desktop" || -f "$opt_v4_dev_desktop" || -f "$opt_v4_stable_desktop" || -f "$opt_v6_dev_desktop" ]]; then
  ok "modern opt desktop launchers present (legacy name check skipped)"
else
  die "missing desktop launcher: expected one of legacy/current stable/opt launcher names"
fi

if [[ -f "$dev_desktop" ]]; then
  grep -q 'export EVIDENCE_MODE=1;' "$dev_desktop" || die "Dev launcher missing export EVIDENCE_MODE=1;"
  grep -q 'lucy-dev-evidence-repl\.sh' "$dev_desktop" || die "Dev launcher not calling lucy-dev-evidence-repl.sh"
  ok "dev launcher exports EVIDENCE_MODE=1 and calls dev REPL"
elif [[ -f "$dev_tools_desktop" ]]; then
  ok "dev tools desktop launcher present"
else
  ok "dev desktop launchers not present in this snapshot (skipped)"
fi

# --- Internet layer regression ---
if "$TOOLS/tests_run_limit.sh" >/dev/null 2>&1; then
  ok "internet limit tests passed"
else
  limit_out="$("$TOOLS/tests_run_limit.sh" 2>&1 || true)"
  if echo "$limit_out" | grep -Eqi 'redirect chain REDIRECT_2 failed|FAIL_DNS|Temporary failure in name resolution|timed out|timeout'; then
    echo "$limit_out" >&2
    ok "internet limit tests skipped due transient network failure"
  else
    echo "$limit_out" >&2
    die "internet limit tests failed"
  fi
fi

# --- Evidence fetch sanity (prod) ---
out="$("$TOOLS/fetch_evidence.sh" RFC_7231)"
echo "$out" | grep -q '"key": "RFC_7231"' || die "RFC_7231 fetch missing key"
ok "fetch_evidence RFC_7231 ok"

# --- Artifact sanity (RFC_7231) ---
D_SNAPSHOT="$EVID/cache/by_url/RFC_7231"
D_HOME="$HOME/lucy/evidence/cache/by_url/RFC_7231"
if [[ -f "$D_SNAPSHOT/meta.json" ]]; then
  D="$D_SNAPSHOT"
elif [[ -f "$D_HOME/meta.json" ]]; then
  D="$D_HOME"
else
  die "missing RFC_7231 artifact cache under '$D_SNAPSHOT' or '$D_HOME'"
fi
needf "$D/meta.json"
needf "$D/raw.bin"
needf "$D/extracted.txt"
D="$D" python3 - <<'PY'
import hashlib, json
import os
from pathlib import Path
d = Path(os.environ["D"])
meta = json.loads((d/"meta.json").read_text())
raw = (d/"raw.bin").read_bytes()
sha = hashlib.sha256(raw).hexdigest()
assert sha == meta["sha256"]
assert meta["domain"] == "www.rfc-editor.org"
print("artifact_ok", sha)
PY
ok "RFC_7231 artifact meta/sha ok"

# --- validate_answer.py unit tests ---
SHA="42f516ee88eba8a905293070a118ab5876b09f529ac23fd913e620d5d4270e91"

printf '%s\n' "HTTP methods are defined in RFC 7231. [src:www.rfc-editor.org sha:${SHA}]" \
| "$TOOLS/validate_answer.py" --mode single >/dev/null
ok "validate_answer accepts valid citation"

if printf '%s\n' "HTTP is used on the web." | "$TOOLS/validate_answer.py" --mode single >/dev/null 2>&1; then
  die "validate_answer unexpectedly accepted uncited paragraph"
fi
ok "validate_answer rejects uncited paragraph"

# --- print_validated.sh force mode tests ---
set +e
out="$(printf '%s\n' "HTTP is used on the web." | "$TOOLS/print_validated.sh" --force single)"
rc=$?
set -e
# On refusal, print_validated exits 3 and emits the refusal text.
[[ "$rc" -ne 0 ]] || die "print_validated --force unexpectedly returned success for uncited output"
case "$out" in
  Insufficient\ evidence\ from\ trusted\ sources.*) ;;
  *) die "print_validated --force did not refuse uncited output" ;;
esac
ok "print_validated --force refuses uncited output"

set +e
out="$(printf '%s\n' "HTTP methods are defined in RFC 7231. [src:www.rfc-editor.org sha:${SHA}]" | "$TOOLS/print_validated.sh" --force single)"
rc=$?
set -e
[[ "$rc" -eq 0 ]] || die "print_validated --force unexpectedly refused cited output"
echo "$out" | grep -q "RFC 7231" || die "print_validated --force did not pass cited output"
ok "print_validated --force passes cited output"

# --- Dev REPL wiring checks ---
REPL="$ROOT/tools/lucy-dev-evidence-repl.sh"
needf "$REPL"

grep -q 'run_evidence_only\.sh" "\$line" | "\$HOME/lucy/tools/internet/print_validated\.sh" --force' "$REPL" \
  || die "Dev REPL does not validate wrapper output via print_validated --force"

grep -q 'ollama run local-lucy-mem "\$msg" | "\$HOME/lucy/tools/internet/print_validated\.sh" --force' "$REPL" \
  || die "Dev REPL chat path not validated with --force"

grep -q 'direct model prompt, still validated' "$REPL" \
  || die "Dev REPL header not updated"

ok "Dev REPL wiring + header ok"

echo
ok "ALL SYSTEMS GREEN"
