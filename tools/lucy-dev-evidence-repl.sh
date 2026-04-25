#!/usr/bin/env bash
# ROLE: LEGACY / DEPRECATED SURFACE
# Retained for compatibility/history; do not use for new workflows.
# Preferred replacement: tools/start_local_lucy_opt_experimental_v6_dev.sh
set -euo pipefail

echo "=== Local Lucy DEV (EVIDENCE-ONLY REPL) ==="
echo "Allowed commands: summarize: / rewrite: / extract: (wrapper enforced)";
echo "Also: chat: <message> (direct model prompt, still validated)"
echo "Type /quit to exit."
echo

# Envelope-enforced evidence mode (model cannot toggle).
export EVIDENCE_MODE=1


while true; do
  printf "dev> "
  if ! IFS= read -r line; then
    echo
    exit 0
  fi

  # exit
  if [[ "$line" == "/quit" || "$line" == "/exit" ]]; then
    exit 0
  fi

  # ignore blank
  [[ -z "${line// }" ]] && continue

  # enforce evidence-only wrapper
  # prompt-only passthrough
  if [[ "$line" =~ ^[Cc][Hh][Aa][Tt]:[[:space:]]*(.*)$ ]]; then
    msg="${BASH_REMATCH[1]}"
    ollama run local-lucy-mem "$msg" | "$HOME/lucy/tools/internet/print_validated.sh" --force single || true
    echo
    continue
  fi
  "$HOME/lucy/tools/run_evidence_only.sh" "$line" | "$HOME/lucy/tools/internet/print_validated.sh" --force single || true
  echo
done
