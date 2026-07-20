#!/usr/bin/env bash
set -euo pipefail

normalize_query_policy_text() {
  printf '%s' "${1:-}" \
    | tr '[:upper:]' '[:lower:]' \
    | sed -E 's/^[[:space:]]+|[[:space:]]+$//g; s/[[:space:]]+/ /g'
}

normalize_for_medical_match() {
  local s
  s="$(normalize_query_policy_text "${1:-}")"
  s="$(printf '%s' "$s" | sed -E 's/\barrhythia\b/arrhythmia/g; s/\beffect\b/affect/g')"
  s="$(printf '%s' "$s" | sed -E 's/\bside affects\b/side effects/g; s/\bside affect\b/side effect/g')"
  printf '%s' "$s"
}

shared_human_medication_high_risk_query() {
  local helper
  helper="${LUCY_MEDICAL_QUERY_HEURISTICS_TOOL:-${LUCY_ROOT:-$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)}/tools/router_py/medical_query_heuristics_cli.py}"
  [[ -f "${helper}" ]] || return 2
  command -v python3 >/dev/null 2>&1 || return 2
  python3 "${helper}" --is-human-medication-high-risk "${1:-}" >/dev/null 2>&1
}

is_time_sensitive_or_web_query() {
  local q_norm
  q_norm="$(normalize_query_policy_text "${1:-}")"
  if printf '%s' "${q_norm}" | grep -Eqi '(^|[^[:alnum:]_])(news|headline|headlines|breaking|latest|recent|today|current|update|updates|new shah|source|sources|citation|citations|evidence|verify|wikipedia|wiki|fetch|browse|search web|website|url|http)([^[:alnum:]_]|$)'; then
    return 0
  fi
  if printf '%s' "${q_norm}" | grep -Eqi '(^|[^[:alnum:]_])(price|stock|quote|market|inflation|exchange rate|currency|fx|weather|temperature|schedule)([^[:alnum:]_]|$)'; then
    return 0
  fi
  return 1
}

is_medical_high_risk_query() {
  local q_norm shared_rc
  q_norm="$(normalize_for_medical_match "${1:-}")"
  if shared_human_medication_high_risk_query "${1:-}"; then
    shared_rc=0
  else
    shared_rc=$?
  fi
  if [[ "${shared_rc}" -eq 0 ]]; then
    return 0
  fi
  if [[ "${shared_rc}" -eq 2 ]] && printf '%s' "${q_norm}" | grep -Eqi '(^|[^a-z])(tadalafil|tadalifil|cialis|viagra|sildenafil|vardenafil|metformin|statin|insulin|ibuprofen|acetaminophen|paracetamol|arrhythmia|afib|qt|palpitations|dose|dosage|mg|side effect|side effects|contraindication|contraindications|interaction|interactions|medication|drug|drugs|alcohol|covered by insurance|hmo|kupat holim|hypertension|antihypertensive)([^a-z]|$)|react[[:space:]]+with'; then
    return 0
  fi
  if printf '%s' "${q_norm}" | grep -Eqi '(^|[^[:alnum:]_])(dog|dogs|cat|cats|pet|pets|puppy|puppies|kitten|kittens)([^[:alnum:]_]|$)' \
    && printf '%s' "${q_norm}" | grep -Eqi '(safe to feed|safe for|safe to give|toxic|poison|poisonous|can[[:space:]]+.*eat|feed[[:space:]]+(him|her|them|my[[:space:]]+(dog|cat|pet))|healthy for|healthier for|good for|bad for|okay for|ok for|suitable for|recommended for)'; then
    return 0
  fi
  if printf '%s' "${q_norm}" | grep -Eqi '(^|[^[:alnum:]_])(dog|dogs|cat|cats|pet|pets|puppy|puppies|kitten|kittens)([^[:alnum:]_]|$)' \
    && printf '%s' "${q_norm}" | grep -Eqi '(vet|veterinarian|symptom|symptoms|vomit|vomiting|diarrhea|diarrhoea|stool|poo|poop|runny stool|runny poo|loose stool|soft stool|lethargy|seizure|seizures|cough|coughing|breathing|limping|pain|fever|not eating|appetite|emergency|urgent|poison|poisoning|toxic|xylitol|chocolate|grapes|raisins|onion|garlic|medication|medicine|drug|drugs|dose|dosage|ibuprofen|acetaminophen|paracetamol|can[[:space:]]+i[[:space:]]+give|what[[:space:]]+should[[:space:]]+i[[:space:]]+do)'; then
    return 0
  fi
  return 1
}

is_memory_unsafe_query() {
  is_time_sensitive_or_web_query "${1:-}" && return 0
  is_medical_high_risk_query "${1:-}" && return 0
  return 1
}

usage() {
  cat <<'USAGE'
Usage:
  query_policy.sh is-memory-unsafe "query text"
  query_policy.sh is-medical-high-risk "query text"
  query_policy.sh is-time-sensitive-or-web "query text"
Exit code 0 means "yes", 1 means "no".
USAGE
}

cmd="${1:-}"
shift || true
q="${*:-}"

case "${cmd}" in
  is-memory-unsafe)
    is_memory_unsafe_query "${q}"
    ;;
  is-medical-high-risk)
    is_medical_high_risk_query "${q}"
    ;;
  is-time-sensitive-or-web)
    is_time_sensitive_or_web_query "${q}"
    ;;
  -h|--help|help|"")
    usage
    exit 2
    ;;
  *)
    echo "ERROR: unknown command: ${cmd}" >&2
    usage >&2
    exit 2
    ;;
esac
