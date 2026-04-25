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
Task: Format the preprocess brief intentionally instead of printing raw lines.
Likely files: tools/start_local_lucy_opt_experimental_v3_dev.sh
Constraints: Keep the launcher behavior unchanged except for preprocess presentation.
EOF

out="$({
  printf 'Implement the task.\n'
  printf '/quit\n'
} | LUCY_RUNTIME_AUTHORITY_ROOT="${MOCK_ROOT}" \
    LUCY_TEST_LOG_FILE="${LOG_FILE}" \
    LUCY_CODEX_PREPROCESS_TASK="Format the preprocess brief intentionally instead of printing raw lines." \
    LUCY_CODEX_PREPROCESS_PROMPT_PATH="${PROMPT_FILE}" \
    "${LAUNCHER}" 2>&1)"

printf '%s\n' "${out}" | grep -q 'Using preprocess task from Codex Launcher\.' || die "preprocess alias notice missing"
[[ -s "${LOG_FILE}" ]] || die "expected lucy_chat to receive rewritten query"
forwarded_query="$(head -n1 "${LOG_FILE}")"
[[ "${forwarded_query}" == "Format the preprocess brief intentionally instead of printing raw lines." ]] || die "launcher did not rewrite preprocess alias query"

ok "launcher rewrites preprocess alias prompts to the handed-off task"
echo "PASS: test_launcher_preprocess_task_alias"
