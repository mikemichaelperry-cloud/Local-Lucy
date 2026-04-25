#!/usr/bin/env bash
set -euo pipefail

TOOLS_DIR="${LUCY_TOOLS_DIR:-$HOME/lucy/tools}"
CACHE_DIR="${LUCY_CACHE_DIR:-$HOME/lucy/cache/evidence}"

BUILD_PACK="$TOOLS_DIR/build_evidence_pack.sh"
PLURALITY="$TOOLS_DIR/enforce_news_plurality.sh"
DIGEST="$TOOLS_DIR/build_news_digest.sh"
NEWS_DET="$TOOLS_DIR/news_answer_deterministic.sh"

COMPOSE="$TOOLS_DIR/compose_from_evidence.sh"
VALIDATE="$TOOLS_DIR/print_validated.sh"

SESSION_ID="${LUCY_SESSION_ID:-default}"
PACK_DIR="$CACHE_DIR/pack_${SESSION_ID}"
EVIDENCE_FILE="$PACK_DIR/evidence_pack.txt"
DOMAINS_FILE="$PACK_DIR/domains.txt"
DIGEST_FILE="$PACK_DIR/news_digest.txt"

usage() {
  cat <<'USAGE'
Usage:
  evidence_answer.sh MODE "QUERY"
MODE: single|news
USAGE
}

main() {
  if [ $# -lt 2 ]; then
    usage
    exit 2
  fi

  mode="$1"
  shift
  query="$*"

  if [ ! -x "$BUILD_PACK" ] || [ ! -x "$VALIDATE" ]; then
    echo "ERROR: missing required tool(s) under $TOOLS_DIR" >&2
    exit 2
  fi

  "$BUILD_PACK" "$PACK_DIR" >/dev/null

  if [ "$mode" = "news" ]; then
    if [ ! -x "$PLURALITY" ] || [ ! -x "$DIGEST" ] || [ ! -x "$NEWS_DET" ]; then
      echo "ERROR: missing news tool(s) under $TOOLS_DIR" >&2
      exit 2
    fi

    "$PLURALITY" "$DOMAINS_FILE" 2 >/dev/null
    "$DIGEST" "$EVIDENCE_FILE" "$DIGEST_FILE" >/dev/null

    "$NEWS_DET" "$DIGEST_FILE" | "$VALIDATE" --force
    exit 0
  fi

  # single mode: still uses model (evidence-only runner)
  if [ ! -x "$COMPOSE" ]; then
    echo "ERROR: missing compose tool: $COMPOSE" >&2
    exit 2
  fi

  "$COMPOSE" "$mode" "$query" "$EVIDENCE_FILE" | "$VALIDATE" --force
}

main "$@"
