#!/usr/bin/env bash
set -euo pipefail

TOOLS_DIR="${LUCY_TOOLS_DIR:-$HOME/lucy/tools}"
RUNNER="$TOOLS_DIR/run_evidence_only.sh"

usage() {
  cat <<'USAGE'
Usage:
  compose_from_evidence.sh MODE QUERY EVIDENCE_FILE
MODE: single|news
Outputs:
  BEGIN_VALIDATED
  <answer text>
  END_VALIDATED
USAGE
}

main() {
  if [ $# -ne 3 ]; then
    usage
    exit 2
  fi

  mode="$1"
  query="$2"
  evidence_file="$3"

  if [ ! -x "$RUNNER" ]; then
    echo "ERROR: missing runner: $RUNNER" >&2
    exit 2
  fi

  if [ ! -f "$evidence_file" ]; then
    echo "ERROR: missing evidence file: $evidence_file" >&2
    exit 2
  fi

  export LUCY_EVIDENCE_FILE="$evidence_file"

  doms=""
  if [ -n "${LUCY_DOMAINS_FILE:-}" ] && [ -f "$LUCY_DOMAINS_FILE" ]; then
    doms="$(tr "\n" " " < "$LUCY_DOMAINS_FILE" | tr -s " " " " | sed -e "s/[[:space:]]\+$//")"
  fi

  # Deterministic instruction header for the model.
  # Note: We do NOT allow URLs; citations are by DOMAIN only.
  if [ "$mode" = "news" ]; then
    instr="Use only @EVIDENCE (a structured digest). Do not refuse. Output: Summary: <one sentence>. Key items: - <3 to 10 bullets, each includes DOMAIN and DATE if present>. Conflicts/uncertainty: <one sentence or None>. Sources: <copy SOURCES= list from @EVIDENCE>. No URLs. Never mention tools/internet/browsing. Query: $query"
  elif [ "${LUCY_POLICY_VALIDATION_PROFILE:-}" = "policy_global_recent" ] && [ "${LUCY_POLICY_VALIDATION_ALLOW_BOUNDED:-0}" = "1" ]; then
    instr="Use only @EVIDENCE. This is a recent policy/regulation query with enough trusted support for a bounded answer. Do not claim completeness. If one requested domain is unsupported or the interaction claim is speculative, output exactly: Insufficient evidence from trusted sources. Otherwise output exactly this format: Summary: Based on current trusted sources, <2 to 4 sentences with cautious wording>. Key points: - <1 to 3 bounded bullets grounded in the evidence only>. Limits: <1 sentence naming what remains uncertain or partial>. Sources: <copy SOURCES= list from @EVIDENCE>. No URLs. Never imply certainty beyond current trusted sources. Query: $query"
  else
    instr="Use only @EVIDENCE. If insufficient, output exactly: Insufficient evidence from trusted sources. Otherwise answer concisely. No URLs. Query: $query"
  fi

  echo "BEGIN_VALIDATED"
  "$RUNNER" "rewrite: $instr @EVIDENCE"
  echo "END_VALIDATED"
}

main "$@"
