#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"
LIFECYCLE_TOOL="${ROOT}/tools/runtime_lifecycle.py"

ok(){ echo "OK: $*"; }
die(){ echo "FAIL: $*" >&2; exit 1; }

[[ -f "${LIFECYCLE_TOOL}" ]] || die "missing lifecycle tool: ${LIFECYCLE_TOOL}"

TMPD="$(mktemp -d)"
trap 'rm -rf "${TMPD}"' EXIT

STATE_FILE="${TMPD}/runtime_lifecycle.json"
LOG_FILE="${TMPD}/runtime_lifecycle.log"
LAUNCHER_FILE="${TMPD}/mock_launcher.sh"

cat > "${LAUNCHER_FILE}" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
trap 'exit 0' TERM INT
echo "mock launcher boot"
while true; do
  sleep 1
done
SH
chmod +x "${LAUNCHER_FILE}"

status_json="$(
  python3 "${LIFECYCLE_TOOL}" \
    --lifecycle-file "${STATE_FILE}" \
    --launcher-path "${LAUNCHER_FILE}" \
    --log-file "${LOG_FILE}" \
    status
)"
python3 - <<'PY' "${status_json}"
import json
import sys
payload = json.loads(sys.argv[1])
assert payload["running"] is False
assert payload["status"] == "stopped"
PY

start_json="$(
  python3 "${LIFECYCLE_TOOL}" \
    --lifecycle-file "${STATE_FILE}" \
    --launcher-path "${LAUNCHER_FILE}" \
    --log-file "${LOG_FILE}" \
    start
)"
python3 - <<'PY' "${start_json}" "${STATE_FILE}"
import json
import os
import sys
from pathlib import Path

payload = json.loads(sys.argv[1])
persisted = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
assert payload["running"] is True
assert payload["status"] == "running"
assert isinstance(payload["pid"], int) and payload["pid"] > 0
assert isinstance(payload["runner_pid"], int) and payload["runner_pid"] > 0
assert persisted["running"] is True
assert persisted["status"] == "running"
os.kill(payload["runner_pid"], 0)
os.kill(payload["pid"], 0)
PY

start_again_json="$(
  python3 "${LIFECYCLE_TOOL}" \
    --lifecycle-file "${STATE_FILE}" \
    --launcher-path "${LAUNCHER_FILE}" \
    --log-file "${LOG_FILE}" \
    start
)"
python3 - <<'PY' "${start_json}" "${start_again_json}"
import json
import sys
first = json.loads(sys.argv[1])
second = json.loads(sys.argv[2])
assert first["runner_pid"] == second["runner_pid"]
assert first["pid"] == second["pid"]
assert second["running"] is True
PY

status_running_json="$(
  python3 "${LIFECYCLE_TOOL}" \
    --lifecycle-file "${STATE_FILE}" \
    --launcher-path "${LAUNCHER_FILE}" \
    --log-file "${LOG_FILE}" \
    status
)"
python3 - <<'PY' "${status_running_json}"
import json
import sys
payload = json.loads(sys.argv[1])
assert payload["running"] is True
assert payload["status"] == "running"
PY

stop_json="$(
  python3 "${LIFECYCLE_TOOL}" \
    --lifecycle-file "${STATE_FILE}" \
    --launcher-path "${LAUNCHER_FILE}" \
    --log-file "${LOG_FILE}" \
    stop
)"
python3 - <<'PY' "${stop_json}" "${STATE_FILE}"
import json
import sys
from pathlib import Path

payload = json.loads(sys.argv[1])
persisted = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
assert payload["running"] is False
assert payload["status"] == "stopped"
assert payload["pid"] is None
assert persisted["running"] is False
assert persisted["status"] == "stopped"
PY

stop_again_json="$(
  python3 "${LIFECYCLE_TOOL}" \
    --lifecycle-file "${STATE_FILE}" \
    --launcher-path "${LAUNCHER_FILE}" \
    --log-file "${LOG_FILE}" \
    stop
)"
python3 - <<'PY' "${stop_again_json}"
import json
import sys
payload = json.loads(sys.argv[1])
assert payload["running"] is False
assert payload["status"] == "stopped"
PY

[[ -s "${LOG_FILE}" ]] || die "expected lifecycle log output"

ok "runtime_lifecycle start/status/stop manages authoritative lifecycle truth and clean no-op cases"
echo "PASS: test_runtime_lifecycle_endpoint"
