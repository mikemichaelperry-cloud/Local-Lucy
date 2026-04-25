#!/usr/bin/env bash
set -euo pipefail

# print_validated.sh
# Deterministic output validator/printer.
# Validates a simple envelope-controlled format and blocks obvious authority leaks.

usage() {
  cat <<'USAGE'
Usage:
  print_validated.sh [--force]
Reads candidate output from stdin.
If valid: prints it and exits 0.
If invalid: prints deterministic refusal and exits 3.
USAGE
}

FORCE=0
if [ "${1:-}" = "--force" ]; then
  FORCE=1
fi

buf="$(cat)"

# Required markers
if ! printf "%s" "$buf" | head -n 1 | grep -Fxq "BEGIN_VALIDATED"; then
  echo "VALIDATION_FAILED: missing BEGIN_VALIDATED" >&2
  echo "Insufficient evidence from trusted sources."
  exit 3
fi

if ! printf "%s" "$buf" | tail -n 1 | grep -Fxq "END_VALIDATED"; then
  echo "VALIDATION_FAILED: missing END_VALIDATED" >&2
  echo "Insufficient evidence from trusted sources."
  exit 3
fi

# Disallow URL leakage
if printf "%s" "$buf" | grep -Eqi 'https?://'; then
  echo "VALIDATION_FAILED: URL leakage" >&2
  echo "Insufficient evidence from trusted sources."
  exit 3
fi

# Disallow tool leakage hints
if printf "%s" "$buf" | grep -Eqi '(^|[^a-z0-9])tool:'; then
  echo "VALIDATION_FAILED: tool leakage" >&2
  echo "Insufficient evidence from trusted sources."
  exit 3
fi

# Print as-is

# Disallow model disclaimers about lacking access (envelope owns tools).
if printf "%s" "$buf" | grep -Eqi "no internet|no tool access|paste the text|paste the source"; then
  echo "VALIDATION_FAILED: model access disclaimer" >&2
  echo "Insufficient evidence from trusted sources."
  exit 3
fi
printf "%s\n" "$buf"
exit 0
