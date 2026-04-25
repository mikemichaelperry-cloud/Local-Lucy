#!/usr/bin/env bash
set -euo pipefail

usage(){
  cat <<'USAGE'
Usage:
  fx_answer_deterministic.sh EVIDENCE_PACK
Deterministically extracts USD/ILS from allowlisted evidence pack.
USAGE
}

fail(){
  echo "BEGIN_VALIDATED"
  echo "Insufficient evidence from trusted sources."
  echo "Try again in online mode with a fresh query."
  echo "END_VALIDATED"
  exit 0
}

main(){
  if [ $# -ne 1 ]; then usage; exit 2; fi
  pack="$1"
  [ -f "$pack" ] || { echo "ERROR: missing pack: $pack" >&2; exit 2; }

  rate=""
  ts=""

  # Preferred parse: line containing "USD" plus an ISO timestamp ending with Z.
  line="$(grep -E ' USD [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[^[:space:]]*Z ' "$pack" | head -n 1 || true)"
  if [ -n "$line" ]; then
    # Parse tokens: RATE is token before USD; TS is first token that looks like YYYY-MM-DDT...Z after USD.
    # Avoid awk interval regex because mawk here fails on {m}.
    parsed="$(printf '%s\n' "$line" | awk '
    BEGIN{ prev=""; saw=0; found=0; rate=""; ts="" }
    {
      for(i=1;i<=NF;i++){
        tok=$i
        if(saw==0 && tok=="USD"){ rate=prev; saw=1; continue }
        if(saw==1 &&
           tok ~ /^[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T/ &&
           tok ~ /Z$/){
          ts=tok; found=1; break
        }
        prev=tok
      }
    }
    END{
      if(found==1){ print rate "\n" ts; exit 0 }
      exit 1
    }
  ' || true)"
    rate="$(printf '%s' "$parsed" | sed -n '1p')"
    ts="$(printf '%s' "$parsed" | sed -n '2p')"
  fi

  # Fallback 0: compact BOI token stream can look like "3.136USD2026-02-19T...Z".
  if [ -z "$rate" ]; then
    compact="$(grep -Eo '([0-9]|[1-9][0-9])\.[0-9]{2,6}USD[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[^[:space:]]*Z' "$pack" | head -n1 || true)"
    if [ -n "$compact" ]; then
      rate="$(printf '%s' "$compact" | sed -E 's/^(([0-9]|[1-9][0-9])\.[0-9]{2,6})USD.*$/\1/')"
      ts="$(printf '%s' "$compact" | sed -E 's/^.*USD([0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[^[:space:]]*Z)$/\1/')"
    fi
  fi

  # Fallback 1: BOI page tokens often look like "... דולר USD 3.1360 ...".
  if [ -z "$rate" ]; then
    rate="$(grep -Eo 'USD[[:space:]]+[0-9]+\.[0-9]+' "$pack" | head -n1 | awk '{print $2}' || true)"
  fi

  # Fallback 2: alternate order "... 3.1360 USD ...".
  if [ -z "$rate" ]; then
    rate="$(grep -Eo '[0-9]+\.[0-9]+[[:space:]]+USD' "$pack" | head -n1 | awk '{print $1}' || true)"
  fi

  # Timestamp fallback: any ISO-ish UTC token in pack.
  if [ -z "$ts" ]; then
    ts="$(grep -Eo '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[^[:space:]]*Z' "$pack" | head -n1 || true)"
  fi
  if [ -z "$ts" ]; then
    ts="unknown"
  fi

  [ -n "$rate" ] || fail

  echo "BEGIN_VALIDATED"
  echo "USD/ILS (Bank of Israel): $rate"
  echo "As of (UTC): $ts"
  echo "Source: boi.org.il"
  echo "END_VALIDATED"
}

main "$@"
