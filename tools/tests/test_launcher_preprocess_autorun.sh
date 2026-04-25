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
PROMPT_FILE="${TMPD}/preprocess_prompt.txt"
LOG_FILE="${TMPD}/chat_calls.log"
mkdir -p "${MOCK_ROOT}/tools" "${MOCK_ROOT}/tmp" "${MOCK_ROOT}/state"

cat > "${MOCK_ROOT}/lucy_chat.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "${1:-}" >> "${LUCY_TEST_LOG_FILE}"
printf 'ok\n'
SH
chmod +x "${MOCK_ROOT}/lucy_chat.sh"

cat > "${PROMPT_FILE}" <<'EOF'
Active root: /tmp/mock
Task: Implement the handed-off local task automatically.
EOF

out="$({
  printf '/quit\n'
} | LUCY_RUNTIME_AUTHORITY_ROOT="${MOCK_ROOT}" \
    LUCY_TEST_LOG_FILE="${LOG_FILE}" \
    LUCY_CODEX_GATE_DECISION="local_only" \
    LUCY_CODEX_PREPROCESS_TASK="Implement the handed-off local task automatically." \
    LUCY_CODEX_PREPROCESS_PROMPT_PATH="${PROMPT_FILE}" \
    "${LAUNCHER}" 2>&1)"

printf '%s\n' "${out}" | grep -q 'Running preprocess task from Codex Launcher\.' || die "preprocess autorun notice missing"
[[ -s "${LOG_FILE}" ]] || die "expected lucy_chat to receive autorun task"
forwarded_query="$(head -n1 "${LOG_FILE}")"
[[ "${forwarded_query}" == "Implement the handed-off local task automatically." ]] || die "launcher did not autorun preprocess task"

ok "launcher autoruns local-only preprocess tasks"
echo "PASS: test_launcher_preprocess_autorun"
