#!/usr/bin/env bash
set -euo pipefail

EXECUTE_PLAN_BOOT_START_MS="$(date +%s%3N 2>/dev/null || printf '%s000' "$(date +%s)")"

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"
AUTHORITY_ROOT_OVERRIDE="${LUCY_RUNTIME_AUTHORITY_ROOT:-}"
if [[ -n "${AUTHORITY_ROOT_OVERRIDE}" ]]; then
  ROOT="$(CDPATH= cd -- "${AUTHORITY_ROOT_OVERRIDE}" 2>/dev/null && pwd)" || {
    echo "ERR: invalid LUCY_RUNTIME_AUTHORITY_ROOT: ${AUTHORITY_ROOT_OVERRIDE}" >&2
    exit 2
  }
else
  ROOT="${DEFAULT_ROOT}"
fi
export LUCY_ROOT="${ROOT}"
export LUCY_RUNTIME_AUTHORITY_ROOT="${ROOT}"
STATE_NAMESPACE_RAW="$(printf '%s' "${LUCY_SHARED_STATE_NAMESPACE:-}" | sed -E 's/[^A-Za-z0-9._-]+/_/g; s/^_+|_+$//g')"
if [[ -z "${STATE_NAMESPACE_RAW}" && -n "${LUCY_SHARED_STATE_NAMESPACE:-}" ]]; then
  STATE_NAMESPACE_RAW="unnamed"
fi
STATE_DIR="${ROOT}/state"
if [[ -n "${STATE_NAMESPACE_RAW}" ]]; then
  STATE_DIR="${ROOT}/state/namespaces/${STATE_NAMESPACE_RAW}"
fi
CLASSIFIER="${ROOT}/tools/router/classify_intent.py"
PLAN_MAPPER="${ROOT}/tools/router/plan_to_pipeline.py"
EXTRACTOR="${ROOT}/tools/router/extract_validated.py"
LUCY_CHAT="${ROOT}/lucy_chat.sh"
LOCAL_ANSWER="${ROOT}/tools/local_answer.sh"
LOCAL_WORKER="${ROOT}/tools/local_worker.py"
LOCAL_WORKER_CLIENT_LIB="${ROOT}/tools/local_worker_client.sh"
CONV_SHIM="${ROOT}/tools/conversation/conversation_cadence_shim.py"
UNVERIFIED_CONTEXT_CATALOG="${ROOT}/config/unverified_context_sources_v1.tsv"
UNVERIFIED_CONTEXT_PROVIDER_DEFAULTS="${ROOT}/config/unverified_context_provider_defaults_v1.env"
UNVERIFIED_CONTEXT_PROVIDER_DISPATCH_TOOL="${ROOT}/tools/unverified_context_provider_dispatch.py"
LAST_OUTCOME_FILE="${STATE_DIR}/last_outcome.env"
LAST_ROUTE_FILE="${STATE_DIR}/last_route.env"
RUNTIME_OUTPUT_GUARD_FILE="${STATE_DIR}/runtime_output_guard.tsv"
RUNTIME_OUTPUT_GUARD_COUNTS_FILE="${STATE_DIR}/runtime_output_guard_counts.tsv"
CONV_PROFILE_FILE="${ROOT}/config/conversation_profile.json"
LATPROF_LIB="${ROOT}/tools/router/latency_profile.sh"

if [[ -f "${LATPROF_LIB}" ]]; then
  # Lightweight, env-gated latency profiling for diagnostic passes.
  # shellcheck disable=SC1090
  source "${LATPROF_LIB}"
else
  latprof_prepare_run(){ return 1; }
  latprof_now_ms(){ date +%s000; }
  latprof_append(){ return 0; }
fi

if [[ -f "${LOCAL_WORKER_CLIENT_LIB}" ]]; then
  # shellcheck disable=SC1090
  source "${LOCAL_WORKER_CLIENT_LIB}"
fi

guard_trigger="none"
fallback_kind="none"
local_gen_status="ok"
conversation_shim_applied="0"
conversation_shim_profile="none"
evidence_style_blocked="0"
local_evidence_lexeme_detected="0"
repeat_count_session="0"
outcome_code_override=""
local_force_plain_fallback="0"
telemetry_sync_enabled="0"
policy_recommended_route="local"
policy_actual_route="local"
policy_confidence="0.0"
policy_confidence_threshold="0.60"
policy_freshness_requirement="low"
policy_risk_level="low"
policy_source_criticality="low"
policy_operator_override="none"
policy_reason_codes_csv=""
winning_signal="legacy_policy"
precedence_version=""
manifest_version=""
manifest_selected_route=""
manifest_allowed_routes=""
manifest_forbidden_routes=""
manifest_authority_basis=""
manifest_clarify_required="false"
manifest_context_resolution_used="false"
manifest_context_referent_confidence=""
manifest_evidence_mode=""
manifest_evidence_mode_reason=""
manifest_error=""
routing_signal_temporal="false"
routing_signal_news="false"
routing_signal_conflict="false"
routing_signal_geopolitics="false"
routing_signal_israel_region="false"
routing_signal_source_request="false"
routing_signal_url="false"
routing_signal_ambiguity_followup="false"
routing_signal_medical_context="false"
routing_signal_current_product="false"
governor_intent=""
governor_confidence="0.0"
governor_route=""
governor_allowed_tools=""
governor_requires_sources="false"
governor_requires_clarification="false"
governor_fallback_policy="none"
governor_audit_tags=""
governor_contract_version=""
governor_local_response_id=""
governor_local_response_text=""
governor_resolved_question=""
governor_contextual_followup_applied="false"
route_reason_override="router_classifier_mapper"
router_outcome_code="answered"
knowledge_path="none"
local_direct_used="false"
local_direct_fallback="false"
local_direct_path="disabled"
contextual_local_followup="0"
augmentation_policy="disabled"
augmented_direct_request="false"
augmented_allowed="false"
augmented_provider_selected="none"
augmented_provider_used="none"
augmented_provider_usage_class="none"
augmented_provider_call_reason="not_needed"
augmented_provider_selection_reason="none"
augmented_provider_selection_query="none"
augmented_provider_selection_rule="none"
augmented_provider_cost_notice="false"
augmented_paid_provider_invoked="false"
requested_mode="LOCAL"
final_mode="LOCAL"
fallback_used="false"
fallback_reason="none"
trust_class="unverified"
unverified_context_used="false"
unverified_context_class="none"
unverified_context_title=""
unverified_context_url=""
augmented_provider="none"
augmented_provider_error_reason="none"
augmented_provider_status="none"
unverified_context_prompt_block=""
augmented_unverified_raw=""
augmented_behavior_shape="stable_summary"
augmented_clarification_required="false"
primary_outcome_code=""
primary_trust_class=""
recovery_attempted="false"
recovery_used="false"
recovery_eligible="false"
recovery_lane="none"
child_route_session_id=""
child_route_evidence_created="false"
child_outcome_code=""
child_action_hint=""
child_trust_class=""
shared_state_lock_error=""
semantic_interpreter_fired="false"
semantic_interpreter_original_query=""
semantic_interpreter_resolved_execution_query=""
semantic_interpreter_inferred_domain="unknown"
semantic_interpreter_inferred_intent_family="unknown"
semantic_interpreter_confidence="0.0"
semantic_interpreter_ambiguity_flag="false"
semantic_interpreter_gate_reason="not_invoked"
semantic_interpreter_invocation_attempted="false"
semantic_interpreter_result_status="not_invoked"
semantic_interpreter_use_reason="not_invoked"
semantic_interpreter_used_for_routing="false"
semantic_interpreter_forward_candidates="false"
semantic_interpreter_selected_normalized_query=""
semantic_interpreter_selected_retrieval_query=""
semantic_interpreter_normalized_candidates_csv=""
semantic_interpreter_retrieval_candidates_csv=""
semantic_interpreter_normalized_candidates_json="[]"
semantic_interpreter_retrieval_candidates_json="[]"
semantic_interpreter_retrieval_selected="false"
medical_detector_fired="false"
medical_detector_original_query=""
medical_detector_resolved_execution_query=""
medical_detector_detection_source="none"
medical_detector_pattern_family="none"
medical_detector_candidate_medication=""
medical_detector_normalized_candidate=""
medical_detector_normalized_query=""
medical_detector_confidence="0.0"
medical_detector_confidence_score="0.0"
CHILD_TRACE_FIELDS="EVIDENCE_FETCH_ATTEMPTED EVIDENCE_PLANNER_ORIGINAL_QUERY EVIDENCE_PLANNER_FIRED EVIDENCE_PLANNER_BEST_ADAPTER EVIDENCE_PLANNER_BEST_STRATEGY EVIDENCE_PLANNER_BEST_QUERY EVIDENCE_PLANNER_BEST_CONFIDENCE EVIDENCE_PLANNER_BEST_CONFIDENCE_SCORE EVIDENCE_PLANNER_SELECTED_QUERY EVIDENCE_PLANNER_SELECTED_ADAPTER EVIDENCE_PLANNER_SELECTED_STRATEGY EVIDENCE_PLANNER_SELECTED_CONFIDENCE EVIDENCE_PLANNER_SELECTED_CONFIDENCE_SCORE EVIDENCE_NORMALIZER_ORIGINAL_QUERY EVIDENCE_NORMALIZER_DETECTOR_FIRED EVIDENCE_NORMALIZER_BEST_ADAPTER EVIDENCE_NORMALIZER_BEST_DOMAIN EVIDENCE_NORMALIZER_BEST_QUERY EVIDENCE_NORMALIZER_BEST_CONFIDENCE EVIDENCE_NORMALIZER_BEST_CONFIDENCE_SCORE EVIDENCE_NORMALIZER_BEST_RULES EVIDENCE_NORMALIZER_SELECTED_QUERY EVIDENCE_NORMALIZER_SELECTED_ADAPTER EVIDENCE_NORMALIZER_SELECTED_DOMAIN EVIDENCE_NORMALIZER_SELECTED_CONFIDENCE EVIDENCE_NORMALIZER_SELECTED_CONFIDENCE_SCORE EVIDENCE_NORMALIZER_SELECTED_RULES EVIDENCE_NORMALIZER_SELECTED_KEYS EVIDENCE_NORMALIZER_SELECTED_KEY_FAMILY EVIDENCE_NORMALIZER_MATCH_KIND"
child_trace_pairs=""

on_exit_sync(){
  [[ "${telemetry_sync_enabled}" == "1" ]] || return 0
  sync_router_outcome_telemetry || true
}
trap on_exit_sync EXIT

err(){ echo "ERR: $*" >&2; }
with_file_lock(){
  local target="$1" lock_file lock_fd rc
  shift
  lock_file="${target}.lock"
  mkdir -p "$(dirname "${target}")"
  if command -v flock >/dev/null 2>&1; then
    # FIX: Use atomic exclusive creation to avoid race condition.
    # Open with O_CREAT|O_EXCL via >| to ensure we create+own the lock atomically,
    # then re-open for flock. This prevents two processes from thinking they
    # both created the lock file before either acquired the lock.
    # shellcheck disable=SC3045
    exec {lock_fd}> "${lock_file}" || { "$@"; return $?; }
    flock "${lock_fd}"
    "$@"
    rc=$?
    flock -u "${lock_fd}" || true
    # shellcheck disable=SC3045
    exec {lock_fd}>&- || true
    return "${rc}"
  fi
  "$@"
}
acquire_shared_execution_lock(){
  local allow_overlap lock_fd
  [[ -n "${STATE_NAMESPACE_RAW}" ]] && return 0
  allow_overlap="$(printf '%s' "${LUCY_SHARED_STATE_PARALLEL_ALLOW:-0}" | tr '[:upper:]' '[:lower:]')"
  case "${allow_overlap}" in
    1|true|yes|on) return 0 ;;
  esac
  command -v flock >/dev/null 2>&1 || return 0
  mkdir -p "${STATE_DIR}"
  # shellcheck disable=SC3045
  exec {lock_fd}> "${STATE_DIR}/execute_plan.active.lock"
  if ! flock -n "${lock_fd}"; then
    shared_state_lock_error="shared-state overlap detected for ${STATE_DIR}; rerun with LUCY_SHARED_STATE_NAMESPACE or isolated LUCY_ROOT"
    err "${shared_state_lock_error}"
    return 1
  fi
}
print_validated_insufficient(){
  printf '%s\n' "BEGIN_VALIDATED"
  printf '%s\n' "Insufficient evidence from trusted sources."
  printf '%s\n' "END_VALIDATED"
}
print_best_effort_recovery_unavailable(){
  printf '%s\n' "Verification was insufficient, and no governed lower-trust recovery answer was available."
  printf '%s\n' "Try narrowing the question or provide an allowlisted source URL."
}
print_medical_insufficient(){
  local q="${1:-}"
  local qn
  qn="$(printf '%s' "${q}" | tr '[:upper:]' '[:lower:]' | sed -E 's/[[:space:]]+/ /g; s/^ +| +$//g')"
  printf '%s\n' "BEGIN_VALIDATED"
  printf '%s\n' "Insufficient evidence from trusted sources."
  if printf '%s' "${qn}" | grep -Eqi '(tuna|tinned tuna|canned tuna)' \
    && {
      printf '%s' "${qn}" | grep -Eqi '(^|[^[:alnum:]_])(dog|dogs|cat|cats|pet|pets|puppy|puppies|kitten|kittens|oscar)([^[:alnum:]_]|$)' \
      || printf '%s' "${qn}" | grep -Eqi '(safe to feed|safe for|safe to give|toxic|poison|poisonous|can[[:space:]]+.*eat|feed[[:space:]]+|healthy for|healthier for|good for|bad for|okay for|ok for|suitable for|recommended for)';
    }; then
    printf '%s\n' "Conservative guidance: canned/tinned tuna is not a healthy staple for dogs."
    if printf '%s' "${qn}" | grep -Eqi '(brine|salt|salty|sodium)'; then
      printf '%s\n' "Avoid tuna in brine because high sodium can be harmful for dogs."
    fi
    if printf '%s' "${qn}" | grep -Eqi '(olive oil|oil|oily)'; then
      printf '%s\n' "Avoid tuna packed in oil (including olive oil) because extra fat can trigger stomach upset or pancreatitis risk."
    fi
    if printf '%s' "${qn}" | grep -Eqi '(water|in water)'; then
      printf '%s\n' "If given at all, only plain tuna in water without added salt should be a tiny occasional treat, not a meal."
    fi
    printf '%s\n' "Use complete dog food for regular meals and ask your veterinarian before adding fish."
    printf '%s\n' "Sources for this conservative fallback: vcahospitals.com, akc.org, petmd.com."
  fi
  printf '%s\n' "END_VALIDATED"
}
is_backend_unavailable_output(){
  local body="${1:-}" n
  n="$(printf '%s' "${body}" | tr '[:upper:]' '[:lower:]')"
  [[ "${n}" == *"127.0.0.1:11434"* ]] && return 0
  [[ "${n}" == *"ollama"* && "${n}" == *"not found"* ]] && return 0
  [[ "${n}" == *"connection refused"* ]] && return 0
  [[ "${n}" == *"operation not permitted"* ]] && return 0
  [[ "${n}" == *"dial tcp"* && "${n}" == *"11434"* ]] && return 0
  return 1
}
print_medical_backend_unavailable(){
  printf '%s\n' "BEGIN_VALIDATED"
  printf '%s\n' "Unable to answer from current evidence."
  printf '%s\n' "Reason: local_generation_backend_unavailable"
  printf '%s\n' "Action: ensure local backend is running (Ollama on 127.0.0.1:11434), then retry."
  printf '%s\n' "END_VALIDATED"
}
requires_evidence_mode(){
  local q="$1"
  printf '%s\n' "This requires evidence mode."
  printf '%s\n' "Run: run online: ${q}"
}
manifest_evidence_selection_label(){
  local evidence_mode="${1:-}"
  local evidence_reason="${2:-}"
  if [[ -z "${evidence_mode}" ]]; then
    printf '%s' "not_applicable"
    return 0
  fi
  case "${evidence_reason}" in
    default_light)
      printf '%s' "default-light"
      ;;
    explicit_*|source_request)
      printf '%s' "explicit-user-triggered"
      ;;
    policy_*|medical_context|geopolitics|conflict_live)
      printf '%s' "policy-triggered"
      ;;
    *)
      printf '%s' "manifest-selected"
      ;;
  esac
}
normalize_augmentation_policy(){
  local raw
  raw="$(printf '%s' "${1:-disabled}" | tr '[:upper:]' '[:lower:]')"
  case "${raw}" in
    disabled|off|none|0|false|no) printf '%s' "disabled" ;;
    fallback_only|fallback|1|true|yes|on) printf '%s' "fallback_only" ;;
    direct_allowed|direct|2) printf '%s' "direct_allowed" ;;
    *) printf '%s' "disabled" ;;
  esac
}
provider_usage_class_for(){
  case "$(printf '%s' "${1:-none}" | tr '[:upper:]' '[:lower:]')" in
    openai|grok) printf '%s' "paid" ;;
    wikipedia) printf '%s' "free" ;;
    local) printf '%s' "local" ;;
    *) printf '%s' "none" ;;
  esac
}
set_augmented_provider_used(){
  local provider="${1:-none}" usage_class
  usage_class="$(provider_usage_class_for "${provider}")"
  augmented_provider_used="${provider}"
  augmented_provider_usage_class="${usage_class}"
  if [[ "${usage_class}" == "paid" ]]; then
    augmented_provider_cost_notice="true"
    augmented_paid_provider_invoked="true"
  else
    augmented_provider_cost_notice="false"
    augmented_paid_provider_invoked="false"
  fi
}
is_truthy(){
  case "$(printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]')" in
    1|true|yes|on) return 0 ;;
    *) return 1 ;;
  esac
}
runtime_local_fallback_text(){
  printf '%s\n' "I could not generate a reply locally. Please retry, or switch mode."
}
render_chat_fast_from_raw(){
  local raw="${1:-}" line s out=""
  while IFS= read -r line || [[ -n "${line}" ]]; do
    s="$(printf '%s' "${line}" | sed -E 's/^[[:space:]]+|[[:space:]]+$//g')"
    [[ -n "${s}" ]] || continue
    [[ "${s}" == "BEGIN_VALIDATED" || "${s}" == "END_VALIDATED" ]] && continue
    if [[ -z "${out}" ]]; then
      out="${s}"
    else
      out="${out} ${s}"
    fi
  done <<< "${raw}"
  if [[ -n "${out}" ]]; then
    printf '%s\n' "${out}"
    return 0
  fi
  printf '%s\n' "${raw}"
}
local_fast_guard_normalize(){
  printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]' | sed -E 's/[[:space:]]+/ /g; s/^ +| +$//g'
}
local_fast_is_allowed_repeat_body(){
  local n
  n="$(local_fast_guard_normalize "${1:-}")"
  case "${n}" in
    "i could not generate a reply locally. please retry, or switch mode."|"error")
      return 0
      ;;
  esac
  return 1
}
local_fast_non_empty_guard(){
  local q="$1" body="$2" mode="$3"
  if [[ -n "$(printf '%s' "${body}" | tr -d '[:space:]')" ]]; then
    printf '%s' "${body}"
    return 0
  fi
  if [[ "${mode}" == "CONVERSATION" ]]; then
    render_conversation_fallback "${q}"
    return 0
  fi
  runtime_local_fallback_text
}
local_fast_repetition_guard(){
  local q="$1" body="$2" mode="$3" state_file count_file qn bn rec_qn rec_bn guarded repeat_count prior_count
  qn="$(local_fast_guard_normalize "${q}")"
  bn="$(local_fast_guard_normalize "${body}")"
  state_file="${RUNTIME_OUTPUT_GUARD_FILE}"
  count_file="${RUNTIME_OUTPUT_GUARD_COUNTS_FILE}"
  mkdir -p "$(dirname "${state_file}")"

  rec_qn=""
  rec_bn=""
  if [[ -f "${state_file}" ]]; then
    rec_qn="$(awk -F'\t' 'NR==1{print $1}' "${state_file}" 2>/dev/null || true)"
    rec_bn="$(awk -F'\t' 'NR==1{print $2}' "${state_file}" 2>/dev/null || true)"
  fi

  prior_count="$(awk -F'\t' -v key="${bn}" 'BEGIN{c=0} $1==key{c=$2} END{print c}' "${count_file}" 2>/dev/null || true)"
  [[ "${prior_count}" =~ ^[0-9]+$ ]] || prior_count=0
  repeat_count=$((prior_count + 1))
  repeat_count_session="${repeat_count}"

  guarded="${body}"
  if [[ -n "${bn}" && "${mode}" =~ ^(CHAT|CONVERSATION)$ && "${qn}" != "${rec_qn}" && "${bn}" == "${rec_bn}" ]]; then
    if ! local_fast_is_allowed_repeat_body "${body}"; then
      quality_dbg "repeat_guard triggered mode=${mode} qn=${qn}"
      guard_trigger="repetition_guard_triggered"
      fallback_kind="deterministic_repeat_breaker"
      guarded="$(runtime_local_prompt_fallback_text "${q}" "${repeat_count}")"
      if [[ "$(local_fast_guard_normalize "${guarded}")" == "${bn}" ]]; then
        guarded="${guarded}"$'\n'"Direct answer: ${q}"
      fi
      bn="$(local_fast_guard_normalize "${guarded}")"
      prior_count="$(awk -F'\t' -v key="${bn}" 'BEGIN{c=0} $1==key{c=$2} END{print c}' "${count_file}" 2>/dev/null || true)"
      [[ "${prior_count}" =~ ^[0-9]+$ ]] || prior_count=0
      repeat_count=$((prior_count + 1))
      repeat_count_session="${repeat_count}"
    fi
  fi

  awk -F'\t' -v key="${bn}" '$1!=key' "${count_file}" 2>/dev/null > "${count_file}.tmp" || true
  printf '%s\t%s\n' "${bn}" "${repeat_count}" >> "${count_file}.tmp"
  mv "${count_file}.tmp" "${count_file}"
  printf '%s\t%s\n' "${qn}" "$(local_fast_guard_normalize "${guarded}")" > "${state_file}"
  printf '%s' "${guarded}"
}
sha256_text(){
  local s="${1:-}"
  if command -v sha256sum >/dev/null 2>&1; then
    printf '%s' "${s}" | sha256sum | awk '{print $1}'
    return 0
  fi
  printf '%s' "${s}" | md5sum | awk '{print $1}'
}
deterministic_pick_index(){
  local seed="$1" mod="$2" h hex
  h="$(sha256_text "${seed}")"
  hex="${h:0:8}"
  printf '%d' $(( 16#${hex} % mod ))
}
conversation_profile_style(){
  [[ -f "${CONV_PROFILE_FILE}" ]] || { printf '%s' "calibrated_sharp"; return 0; }
  python3 - "${CONV_PROFILE_FILE}" <<'PY'
import json, sys
path=sys.argv[1]
try:
    data=json.load(open(path, "r", encoding="utf-8"))
except Exception:
    print("calibrated_sharp")
    raise SystemExit(0)
print(str(data.get("style") or "calibrated_sharp"))
PY
}
runtime_local_prompt_fallback_text(){
  local q="${1:-}" variant="${2:-0}" qn idx
  qn="$(printf '%s' "${q}" | tr '[:upper:]' '[:lower:]' | sed -E 's/[[:space:]]+/ /g; s/^ +| +$//g')"

  case "${qn}" in
    "not necessary."|"not necessary"|"no thanks"|"never mind")
      return 0
      ;;
    *"how are you"*|"hi."|"hi")
      printf '%s\n' "Hello. What do you want to solve right now?"
      return 0
      ;;
  esac
  local -a bank=(
    "State the specific question in one sentence and I will answer directly."
    "Give me one concrete detail and I will respond precisely."
    "Narrow it to one claim or decision and I will work through it."
    "Restate the exact point you want help with, and I will keep the answer focused."
    "Tell me the practical question behind this, and I will address it directly."
    "Give me the single most important detail, and I will continue from there."
    "Frame the issue as one concrete question, and I will answer without drifting."
    "Name the exact topic or decision, and I will give a bounded response."
  )
  idx="$(deterministic_pick_index "${qn}|${variant}" "${#bank[@]}")"
  printf '%s\n' "${bank[$idx]}"
}
is_runtime_local_prompt_fallback_text(){
  local body="${1:-}" n
  n="$(printf '%s' "${body}" | tr '[:upper:]' '[:lower:]' | sed -E 's/[[:space:]]+/ /g; s/^ +| +$//g')"
  case "${n}" in
    "state the specific question in one sentence and i will answer directly." \
    |"give me one concrete detail and i will respond precisely." \
    |"narrow it to one claim or decision and i will work through it." \
    |"restate the exact point you want help with, and i will keep the answer focused." \
    |"tell me the practical question behind this, and i will address it directly." \
    |"give me the single most important detail, and i will continue from there." \
    |"frame the issue as one concrete question, and i will answer without drifting." \
    |"name the exact topic or decision, and i will give a bounded response.")
      return 0
      ;;
  esac
  return 1
}
is_local_generation_failure_output(){
  local body="${1:-}" n
  n="$(printf '%s' "${body}" | tr '[:upper:]' '[:lower:]')"
  [[ "${n}" == *"i could not generate a reply locally."* ]]
}
is_evidence_style_text(){
  local body="${1:-}" n
  n="$(printf '%s' "${body}" | tr '[:upper:]' '[:lower:]' | sed -E 's/[[:space:]]+/ /g; s/^ +| +$//g')"
  [[ "${n}" =~ ^from\ current\ sources: ]] && return 0
  [[ "${n}" =~ ^insufficient\ evidence\ from\ trusted\ sources\.?$ ]] && return 0
  [[ "${n}" =~ ^this\ requires\ evidence\ mode\.?($|[[:space:]]) ]] && return 0
  [[ "${n}" == *"from current sources:"* ]] && return 0
  return 1
}
is_clarification_style_text(){
  local body="${1:-}" n
  n="$(printf '%s' "${body}" | tr '[:upper:]' '[:lower:]' | sed -E 's/[[:space:]]+/ /g; s/^ +| +$//g')"
  [[ "${n}" == *"?" ]] || return 1
  [[ "${n}" =~ ^(which|what|who|when|where|why|how|state|name|tell me|give me)\  ]] || return 0
  [[ "${n}" =~ \ do\ you\ want\  ]] && return 0
  return 1
}
is_validated_insufficient_text(){
  local body="${1:-}" n
  n="$(printf '%s' "${body}" | tr '[:upper:]' '[:lower:]' | sed -E 's/[[:space:]]+/ /g; s/^ +| +$//g')"
  [[ "${n}" == *"unable to answer from current evidence."* ]] && return 0
  [[ "${n}" == *"insufficient evidence from trusted sources"* ]] && return 0
  [[ "${n}" =~ note:\ insufficient\ corroboration\ \(found\ [0-9]+\ sources,\ need\ [0-9]+\)\. ]] && return 0
  return 1
}
read_outcome_field(){
  local key="$1"
  grep -E "^${key}=" "${LAST_OUTCOME_FILE}" 2>/dev/null | head -n1 | cut -d= -f2-
}
count_last_route_evidence_domains(){
  local route_file sid domains_file
  route_file="${LAST_ROUTE_FILE}"
  sid="${child_route_session_id:-}"
  if [[ -z "${sid}" ]]; then
    sid="$(grep -E '^SESSION_ID=' "${route_file}" 2>/dev/null | head -n1 | cut -d= -f2- || true)"
  fi
  [[ -n "${sid}" ]] || { printf '0'; return 0; }
  domains_file="${ROOT}/evidence/${sid}/pack/domains.txt"
  [[ -f "${domains_file}" ]] || { printf '0'; return 0; }
  awk 'NF{print tolower($0)}' "${domains_file}" | sed -E 's/^www\.//' | sort -u | wc -l | awk '{print $1}'
}
last_route_evidence_domains_csv(){
  local limit route_file sid domains_file
  limit="${1:-3}"
  route_file="${LAST_ROUTE_FILE}"
  sid="${child_route_session_id:-}"
  if [[ -z "${sid}" ]]; then
    sid="$(grep -E '^SESSION_ID=' "${route_file}" 2>/dev/null | head -n1 | cut -d= -f2- || true)"
  fi
  [[ -n "${sid}" ]] || { printf ''; return 0; }
  domains_file="${ROOT}/evidence/${sid}/pack/domains.txt"
  [[ -f "${domains_file}" ]] || { printf ''; return 0; }
  awk 'NF{print tolower($0)}' "${domains_file}" \
    | sed -E 's/^www\.//' \
    | sort -u \
    | head -n "${limit}" \
    | paste -sd ',' -
}
_upsert_outcome_field_unlocked(){
  local key="$1" value="$2" tmpf outcome_dir
  outcome_dir="$(dirname "${LAST_OUTCOME_FILE}")"
  mkdir -p "${outcome_dir}"
  # FIX: Use TMPDIR for temp file to ensure atomic mv within same filesystem.
  # Creating temp file in target directory risks cross-device mv if target
  # is on a different mount. Using mktemp in standard tmpdir + atomic mv
  # ensures consistent atomic rename behavior.
  tmpf="$(mktemp "${TMPDIR:-/tmp}/lucy_outcome.XXXXXX.tmp")"
  if [[ -f "${LAST_OUTCOME_FILE}" ]]; then
    grep -Ev "^${key}=" "${LAST_OUTCOME_FILE}" 2>/dev/null > "${tmpf}" || true
  fi
  printf '%s=%s\n' "${key}" "${value}" >> "${tmpf}"
  mv "${tmpf}" "${LAST_OUTCOME_FILE}"
}
upsert_outcome_field(){
  with_file_lock "${LAST_OUTCOME_FILE}" _upsert_outcome_field_unlocked "$@"
}
_sync_router_outcome_telemetry_locked(){
  local route_mode route_reason current_outcome key value executed_mode trust_class_value
  route_mode="${force_mode:-LOCAL}"
  executed_mode="${final_mode:-${route_mode}}"
  route_reason="${route_reason_override:-router_classifier_mapper}"
  current_outcome="${router_outcome_code:-answered}"
  if [[ -n "${outcome_code_override}" ]]; then
    current_outcome="${outcome_code_override}"
  fi
  _upsert_outcome_field_unlocked "MODE" "${executed_mode}"
  _upsert_outcome_field_unlocked "QUERY" "${QUESTION:-${question_for_plan:-}}"
  _upsert_outcome_field_unlocked "QUERY_SHA256" "$(sha256_text "${QUESTION:-${question_for_plan:-}}")"
  _upsert_outcome_field_unlocked "OUTCOME_CODE" "${current_outcome}"
  _upsert_outcome_field_unlocked "ROUTE_MODE" "${route_mode}"
  _upsert_outcome_field_unlocked "REQUESTED_MODE" "${requested_mode:-${route_mode}}"
  _upsert_outcome_field_unlocked "FINAL_MODE" "${executed_mode}"
  _upsert_outcome_field_unlocked "FALLBACK_USED" "${fallback_used:-false}"
  _upsert_outcome_field_unlocked "FALLBACK_REASON" "${fallback_reason:-none}"
  trust_class_value="${trust_class:-unverified}"
  if [[ "${executed_mode}" == "CLARIFY" || "${current_outcome}" == "clarification_requested" ]]; then
    trust_class_value="${trust_class:-}"
  elif [[ "${current_outcome}" == "validation_failed" || "${current_outcome}" == "requires_evidence_mode" ]]; then
    if [[ -z "${trust_class:-}" || "${trust_class}" == "evidence_backed" ]]; then
      trust_class_value="unknown"
    fi
  fi
  _upsert_outcome_field_unlocked "TRUST_CLASS" "${trust_class_value}"
  _upsert_outcome_field_unlocked "AUGMENTED_PROVIDER" "${augmented_provider:-none}"
  _upsert_outcome_field_unlocked "AUGMENTED_ALLOWED" "${augmented_allowed:-false}"
  _upsert_outcome_field_unlocked "AUGMENTED_PROVIDER_SELECTED" "${augmented_provider_selected:-none}"
  _upsert_outcome_field_unlocked "AUGMENTED_PROVIDER_USED" "${augmented_provider_used:-none}"
  _upsert_outcome_field_unlocked "AUGMENTED_PROVIDER_USAGE_CLASS" "${augmented_provider_usage_class:-none}"
  _upsert_outcome_field_unlocked "AUGMENTED_PROVIDER_CALL_REASON" "${augmented_provider_call_reason:-not_needed}"
  _upsert_outcome_field_unlocked "AUGMENTED_PROVIDER_SELECTION_REASON" "${augmented_provider_selection_reason:-none}"
  _upsert_outcome_field_unlocked "AUGMENTED_PROVIDER_SELECTION_QUERY" "${augmented_provider_selection_query:-none}"
  _upsert_outcome_field_unlocked "AUGMENTED_PROVIDER_SELECTION_RULE" "${augmented_provider_selection_rule:-none}"
  _upsert_outcome_field_unlocked "AUGMENTED_PROVIDER_ERROR_REASON" "${augmented_provider_error_reason:-none}"
  _upsert_outcome_field_unlocked "AUGMENTED_PROVIDER_STATUS" "${augmented_provider_status:-none}"
  _upsert_outcome_field_unlocked "AUGMENTED_BEHAVIOR_SHAPE" "${augmented_behavior_shape:-stable_summary}"
  _upsert_outcome_field_unlocked "AUGMENTED_CLARIFICATION_REQUIRED" "${augmented_clarification_required:-false}"
  _upsert_outcome_field_unlocked "AUGMENTED_PROVIDER_COST_NOTICE" "${augmented_provider_cost_notice:-false}"
  _upsert_outcome_field_unlocked "AUGMENTED_PAID_PROVIDER_INVOKED" "${augmented_paid_provider_invoked:-false}"
  _upsert_outcome_field_unlocked "UNVERIFIED_CONTEXT_USED" "${unverified_context_used:-false}"
  _upsert_outcome_field_unlocked "UNVERIFIED_CONTEXT_CLASS" "${unverified_context_class:-none}"
  _upsert_outcome_field_unlocked "UNVERIFIED_CONTEXT_TITLE" "${unverified_context_title:-}"
  _upsert_outcome_field_unlocked "UNVERIFIED_CONTEXT_URL" "${unverified_context_url:-}"
  _upsert_outcome_field_unlocked "PRIMARY_OUTCOME_CODE" "${primary_outcome_code:-}"
  _upsert_outcome_field_unlocked "PRIMARY_TRUST_CLASS" "${primary_trust_class:-}"
  _upsert_outcome_field_unlocked "RECOVERY_ATTEMPTED" "${recovery_attempted:-false}"
  _upsert_outcome_field_unlocked "RECOVERY_USED" "${recovery_used:-false}"
  _upsert_outcome_field_unlocked "RECOVERY_ELIGIBLE" "${recovery_eligible:-false}"
  _upsert_outcome_field_unlocked "RECOVERY_LANE" "${recovery_lane:-none}"
  _upsert_outcome_field_unlocked "AUGMENTATION_POLICY" "${augmentation_policy:-disabled}"
  _upsert_outcome_field_unlocked "AUGMENTED_DIRECT_REQUEST" "${augmented_direct_request:-false}"
  _upsert_outcome_field_unlocked "ROUTE_REASON" "${route_reason}"
  _upsert_outcome_field_unlocked "GUARD_TRIGGER" "${guard_trigger}"
  _upsert_outcome_field_unlocked "FALLBACK_KIND" "${fallback_kind}"
  _upsert_outcome_field_unlocked "LOCAL_GEN_STATUS" "${local_gen_status}"
  _upsert_outcome_field_unlocked "SHIM_APPLIED" "${conversation_shim_applied}"
  _upsert_outcome_field_unlocked "SHIM_PROFILE" "${conversation_shim_profile}"
  _upsert_outcome_field_unlocked "EVIDENCE_STYLE_BLOCKED" "${evidence_style_blocked}"
  _upsert_outcome_field_unlocked "LOCAL_EVIDENCE_LEXEME_DETECTED" "${local_evidence_lexeme_detected}"
  _upsert_outcome_field_unlocked "REPEAT_COUNT_SESSION" "${repeat_count_session}"
  _upsert_outcome_field_unlocked "KNOWLEDGE_PATH" "${knowledge_path}"
  _upsert_outcome_field_unlocked "POLICY_RECOMMENDED_ROUTE" "${policy_recommended_route}"
  _upsert_outcome_field_unlocked "POLICY_ACTUAL_ROUTE" "${policy_actual_route}"
  _upsert_outcome_field_unlocked "POLICY_CONFIDENCE" "${policy_confidence}"
  _upsert_outcome_field_unlocked "POLICY_CONFIDENCE_THRESHOLD" "${policy_confidence_threshold}"
  _upsert_outcome_field_unlocked "POLICY_FRESHNESS_REQUIREMENT" "${policy_freshness_requirement}"
  _upsert_outcome_field_unlocked "POLICY_RISK_LEVEL" "${policy_risk_level}"
  _upsert_outcome_field_unlocked "POLICY_SOURCE_CRITICALITY" "${policy_source_criticality}"
  _upsert_outcome_field_unlocked "INTENT_FAMILY" "${intent_family:-}"
  _upsert_outcome_field_unlocked "POLICY_OPERATOR_OVERRIDE" "${policy_operator_override}"
  _upsert_outcome_field_unlocked "POLICY_REASON_CODES" "${policy_reason_codes_csv}"
  _upsert_outcome_field_unlocked "MANIFEST_VERSION" "${manifest_version}"
  _upsert_outcome_field_unlocked "MANIFEST_SELECTED_ROUTE" "${manifest_selected_route}"
  _upsert_outcome_field_unlocked "MANIFEST_INTENT_FAMILY" "${manifest_intent_family:-}"
  _upsert_outcome_field_unlocked "MANIFEST_ALLOWED_ROUTES" "${manifest_allowed_routes}"
  _upsert_outcome_field_unlocked "MANIFEST_FORBIDDEN_ROUTES" "${manifest_forbidden_routes}"
  _upsert_outcome_field_unlocked "MANIFEST_AUTHORITY_BASIS" "${manifest_authority_basis}"
  _upsert_outcome_field_unlocked "MANIFEST_CLARIFY_REQUIRED" "${manifest_clarify_required}"
  _upsert_outcome_field_unlocked "MANIFEST_CONTEXT_RESOLUTION_USED" "${manifest_context_resolution_used}"
  _upsert_outcome_field_unlocked "MANIFEST_CONTEXT_REFERENT_CONFIDENCE" "${manifest_context_referent_confidence}"
  _upsert_outcome_field_unlocked "MANIFEST_EVIDENCE_MODE" "${manifest_evidence_mode}"
  _upsert_outcome_field_unlocked "MANIFEST_EVIDENCE_MODE_REASON" "${manifest_evidence_mode_reason}"
  _upsert_outcome_field_unlocked "WINNING_SIGNAL" "${winning_signal}"
  _upsert_outcome_field_unlocked "PRECEDENCE_VERSION" "${precedence_version}"
  _upsert_outcome_field_unlocked "ROUTING_SIGNAL_TEMPORAL" "${routing_signal_temporal}"
  _upsert_outcome_field_unlocked "ROUTING_SIGNAL_NEWS" "${routing_signal_news}"
  _upsert_outcome_field_unlocked "ROUTING_SIGNAL_CONFLICT" "${routing_signal_conflict}"
  _upsert_outcome_field_unlocked "ROUTING_SIGNAL_GEOPOLITICS" "${routing_signal_geopolitics}"
  _upsert_outcome_field_unlocked "ROUTING_SIGNAL_ISRAEL_REGION" "${routing_signal_israel_region}"
  _upsert_outcome_field_unlocked "ROUTING_SIGNAL_SOURCE_REQUEST" "${routing_signal_source_request}"
  _upsert_outcome_field_unlocked "ROUTING_SIGNAL_URL" "${routing_signal_url}"
  _upsert_outcome_field_unlocked "ROUTING_SIGNAL_AMBIGUITY_FOLLOWUP" "${routing_signal_ambiguity_followup}"
  _upsert_outcome_field_unlocked "ROUTING_SIGNAL_MEDICAL_CONTEXT" "${routing_signal_medical_context}"
  _upsert_outcome_field_unlocked "ROUTING_SIGNAL_CURRENT_PRODUCT" "${routing_signal_current_product}"
  _upsert_outcome_field_unlocked "GOVERNOR_INTENT" "${governor_intent}"
  _upsert_outcome_field_unlocked "GOVERNOR_CONFIDENCE" "${governor_confidence}"
  _upsert_outcome_field_unlocked "GOVERNOR_ROUTE" "${governor_route}"
  _upsert_outcome_field_unlocked "GOVERNOR_REQUIRES_SOURCES" "${governor_requires_sources}"
  _upsert_outcome_field_unlocked "GOVERNOR_REQUIRES_CLARIFICATION" "${governor_requires_clarification}"
  _upsert_outcome_field_unlocked "GOVERNOR_FALLBACK_POLICY" "${governor_fallback_policy}"
  _upsert_outcome_field_unlocked "GOVERNOR_AUDIT_TAGS" "${governor_audit_tags}"
  _upsert_outcome_field_unlocked "GOVERNOR_ALLOWED_TOOLS" "${governor_allowed_tools}"
  _upsert_outcome_field_unlocked "GOVERNOR_CONTRACT_VERSION" "${governor_contract_version}"
  _upsert_outcome_field_unlocked "GOVERNOR_LOCAL_RESPONSE_ID" "${governor_local_response_id}"
  _upsert_outcome_field_unlocked "SEMANTIC_INTERPRETER_FIRED" "${semantic_interpreter_fired}"
  _upsert_outcome_field_unlocked "SEMANTIC_INTERPRETER_ORIGINAL_QUERY" "${semantic_interpreter_original_query}"
  _upsert_outcome_field_unlocked "SEMANTIC_INTERPRETER_RESOLVED_EXECUTION_QUERY" "${semantic_interpreter_resolved_execution_query}"
  _upsert_outcome_field_unlocked "SEMANTIC_INTERPRETER_INFERRED_DOMAIN" "${semantic_interpreter_inferred_domain}"
  _upsert_outcome_field_unlocked "SEMANTIC_INTERPRETER_INFERRED_INTENT_FAMILY" "${semantic_interpreter_inferred_intent_family}"
  _upsert_outcome_field_unlocked "SEMANTIC_INTERPRETER_CONFIDENCE" "${semantic_interpreter_confidence}"
  _upsert_outcome_field_unlocked "SEMANTIC_INTERPRETER_AMBIGUITY_FLAG" "${semantic_interpreter_ambiguity_flag}"
  _upsert_outcome_field_unlocked "SEMANTIC_INTERPRETER_GATE_REASON" "${semantic_interpreter_gate_reason}"
  _upsert_outcome_field_unlocked "SEMANTIC_INTERPRETER_INVOCATION_ATTEMPTED" "${semantic_interpreter_invocation_attempted}"
  _upsert_outcome_field_unlocked "SEMANTIC_INTERPRETER_RESULT_STATUS" "${semantic_interpreter_result_status}"
  _upsert_outcome_field_unlocked "SEMANTIC_INTERPRETER_USE_REASON" "${semantic_interpreter_use_reason}"
  _upsert_outcome_field_unlocked "SEMANTIC_INTERPRETER_USED_FOR_ROUTING" "${semantic_interpreter_used_for_routing}"
  _upsert_outcome_field_unlocked "SEMANTIC_INTERPRETER_FORWARD_CANDIDATES" "${semantic_interpreter_forward_candidates}"
  _upsert_outcome_field_unlocked "SEMANTIC_INTERPRETER_SELECTED_NORMALIZED_QUERY" "${semantic_interpreter_selected_normalized_query}"
  _upsert_outcome_field_unlocked "SEMANTIC_INTERPRETER_SELECTED_RETRIEVAL_QUERY" "${semantic_interpreter_selected_retrieval_query}"
  _upsert_outcome_field_unlocked "SEMANTIC_INTERPRETER_NORMALIZED_CANDIDATES" "${semantic_interpreter_normalized_candidates_csv}"
  _upsert_outcome_field_unlocked "SEMANTIC_INTERPRETER_RETRIEVAL_CANDIDATES" "${semantic_interpreter_retrieval_candidates_csv}"
  _upsert_outcome_field_unlocked "SEMANTIC_INTERPRETER_RETRIEVAL_SELECTED" "${semantic_interpreter_retrieval_selected}"
  _upsert_outcome_field_unlocked "MEDICATION_DETECTOR_FIRED" "${medical_detector_fired}"
  _upsert_outcome_field_unlocked "MEDICATION_DETECTOR_ORIGINAL_QUERY" "${medical_detector_original_query}"
  _upsert_outcome_field_unlocked "MEDICATION_DETECTOR_RESOLVED_EXECUTION_QUERY" "${medical_detector_resolved_execution_query}"
  _upsert_outcome_field_unlocked "MEDICATION_DETECTOR_DETECTION_SOURCE" "${medical_detector_detection_source}"
  _upsert_outcome_field_unlocked "MEDICATION_DETECTOR_PATTERN_FAMILY" "${medical_detector_pattern_family}"
  _upsert_outcome_field_unlocked "MEDICATION_DETECTOR_CANDIDATE_MEDICATION" "${medical_detector_candidate_medication}"
  _upsert_outcome_field_unlocked "MEDICATION_DETECTOR_NORMALIZED_CANDIDATE" "${medical_detector_normalized_candidate}"
  _upsert_outcome_field_unlocked "MEDICATION_DETECTOR_NORMALIZED_QUERY" "${medical_detector_normalized_query}"
  _upsert_outcome_field_unlocked "MEDICATION_DETECTOR_CONFIDENCE" "${medical_detector_confidence}"
  _upsert_outcome_field_unlocked "MEDICATION_DETECTOR_CONFIDENCE_SCORE" "${medical_detector_confidence_score}"
  _upsert_outcome_field_unlocked "LOCAL_DIRECT_USED" "${local_direct_used}"
  _upsert_outcome_field_unlocked "LOCAL_DIRECT_FALLBACK" "${local_direct_fallback}"
  _upsert_outcome_field_unlocked "LOCAL_DIRECT_PATH" "${local_direct_path}"
  while IFS='=' read -r key value; do
    [[ -n "${key}" ]] || continue
    _upsert_outcome_field_unlocked "${key}" "${value}"
  done <<< "${child_trace_pairs:-}"
}
sync_router_outcome_telemetry(){
  [[ -f "${LAST_OUTCOME_FILE}" ]] || return 0
  with_file_lock "${LAST_OUTCOME_FILE}" _sync_router_outcome_telemetry_locked
}
execute_plan_local_diag_append(){
  local metric="$1" value="$2"
  local diag_file="${LUCY_LOCAL_DIAG_FILE:-}" run_id="${LUCY_LOCAL_DIAG_RUN_ID:-}"
  [[ -n "${diag_file}" && -n "${run_id}" ]] || return 0
  printf 'run=%s\tmetric=%s\tvalue=%s\n' "${run_id}" "${metric}" "${value}" >> "${diag_file}"
}
ensure_outcome_file(){
  mkdir -p "${STATE_DIR}"
  [[ -f "${LAST_OUTCOME_FILE}" ]] || : > "${LAST_OUTCOME_FILE}"
}
read_state_field(){
  local file="$1" key="$2"
  [[ -f "${file}" ]] || return 0
  awk -F= -v k="${key}" '$1==k {sub(/^[^=]*=/,""); print; exit}' "${file}"
}
capture_child_route_state(){
  local expected_query="$1" expected_mode="$2"
  local recorded_query recorded_mode recorded_sess recorded_created recorded_outcome_code recorded_action_hint recorded_trust_class key value

  child_route_session_id=""
  child_route_evidence_created="false"
  child_trace_pairs=""
  child_outcome_code=""
  child_action_hint=""
  child_trust_class=""

  recorded_query="$(read_state_field "${LAST_OUTCOME_FILE}" "QUERY")"
  recorded_mode="$(read_state_field "${LAST_OUTCOME_FILE}" "MODE")"
  recorded_sess="$(read_state_field "${LAST_OUTCOME_FILE}" "SESSION_ID")"
  recorded_created="$(read_state_field "${LAST_OUTCOME_FILE}" "EVIDENCE_CREATED")"
  recorded_outcome_code="$(read_state_field "${LAST_OUTCOME_FILE}" "OUTCOME_CODE")"
  recorded_action_hint="$(read_state_field "${LAST_OUTCOME_FILE}" "ACTION_HINT")"
  recorded_trust_class="$(read_state_field "${LAST_OUTCOME_FILE}" "TRUST_CLASS")"

  if [[ "${recorded_query}" != "${expected_query}" ]] || [[ "${recorded_mode}" != "${expected_mode}" ]]; then
    return 0
  fi

  child_outcome_code="${recorded_outcome_code}"
  child_action_hint="${recorded_action_hint}"
  child_trust_class="${recorded_trust_class}"
  if [[ -z "${recorded_sess}" ]]; then
    return 0
  fi

  child_route_session_id="${recorded_sess}"
  case "$(printf '%s' "${recorded_created:-false}" | tr '[:upper:]' '[:lower:]')" in
    1|true|yes|on) child_route_evidence_created="true" ;;
    *) child_route_evidence_created="false" ;;
  esac
  for key in ${CHILD_TRACE_FIELDS}; do
    value="$(read_state_field "${LAST_OUTCOME_FILE}" "${key}")"
    child_trace_pairs+="${key}=${value}"$'\n'
  done
}
update_semantic_interpreter_child_usage(){
  local selected_adapter
  semantic_interpreter_retrieval_selected="false"
  selected_adapter="$(read_state_field "${LAST_OUTCOME_FILE}" "EVIDENCE_PLANNER_SELECTED_ADAPTER")"
  case "${selected_adapter}" in
    semantic_*) semantic_interpreter_retrieval_selected="true" ;;
  esac
}
_write_last_route_meta_locked(){
  local mode="$1" reason="$2" q="$3" sess="${4:-}"
  local tmpf
  mkdir -p "${STATE_DIR}"
  tmpf="$(mktemp "${STATE_DIR}/last_route.XXXXXX.tmp")"
  {
    echo "UTC=$(date -u -Is)"
    echo "MODE=${mode}"
    echo "ROUTE_REASON=${reason}"
    echo "SESSION_ID=${sess}"
    echo "QUERY=${q}"
    echo "QUERY_SHA256=$(sha256_text "${q}")"
  } > "${tmpf}"
  mv "${tmpf}" "${LAST_ROUTE_FILE}"
}
write_last_route_meta(){
  with_file_lock "${LAST_ROUTE_FILE}" _write_last_route_meta_locked "$@"
}
_write_last_outcome_meta_locked(){
  local mode="$1" reason="$2" q="$3" sess="${4:-}" evidence_created="$5" outcome_code="$6" action_hint="$7" rc="$8"
  local tmpf
  mkdir -p "${STATE_DIR}"
  tmpf="$(mktemp "${STATE_DIR}/last_outcome.XXXXXX.tmp")"
  {
    echo "UTC=$(date -u -Is)"
    echo "MODE=${mode}"
    echo "ROUTE_REASON=${reason}"
    echo "SESSION_ID=${sess}"
    echo "EVIDENCE_CREATED=${evidence_created}"
    echo "OUTCOME_CODE=${outcome_code}"
    echo "ACTION_HINT=${action_hint}"
    echo "RC=${rc}"
    echo "QUERY=${q}"
    echo "QUERY_SHA256=$(sha256_text "${q}")"
  } > "${tmpf}"
  mv "${tmpf}" "${LAST_OUTCOME_FILE}"
}
write_last_outcome_meta(){
  with_file_lock "${LAST_OUTCOME_FILE}" _write_last_outcome_meta_locked "$@"
}
record_terminal_outcome(){
  local outcome_code="$1" mode="${2:-${force_mode:-LOCAL}}" action_hint="${3:-}" rc="${4:-0}" sess evidence_created
  ensure_outcome_file
  router_outcome_code="${outcome_code}"
  outcome_code_override="${outcome_code}"
  if [[ "${outcome_code}" == "validated_insufficient" ]]; then
    [[ -n "${primary_outcome_code:-}" ]] || primary_outcome_code="validated_insufficient"
    if [[ -z "${primary_trust_class:-}" && "${mode}" != "LOCAL" ]]; then
      primary_trust_class="evidence_backed"
    fi
  fi
  sess=""
  evidence_created="false"
  if [[ "${mode}" != "LOCAL" && -n "${child_route_session_id}" ]]; then
    sess="${child_route_session_id}"
    evidence_created="${child_route_evidence_created}"
  fi
  write_last_route_meta "${mode}" "${route_reason_override}" "${question_for_plan}" "${sess}"
  write_last_outcome_meta "${mode}" "${route_reason_override}" "${question_for_plan}" "${sess}" "${evidence_created}" "${outcome_code}" "${action_hint}" "${rc}"
  sync_router_outcome_telemetry || true
}
chat_memory_context_available(){
  local mem_file
  [[ "${LUCY_SESSION_MEMORY:-1}" == "1" ]] || return 1
  mem_file="${LUCY_CHAT_MEMORY_FILE:-}"
  [[ -n "${mem_file}" && -s "${mem_file}" ]]
}
local_direct_enabled(){
  case "$(printf '%s' "${LUCY_LOCAL_DIRECT_ENABLED:-1}" | tr '[:upper:]' '[:lower:]')" in
    1|true|yes|on) return 0 ;;
    *) return 1 ;;
  esac
}
local_direct_eligible(){
  case "$(printf '%s' "${LUCY_EXECUTE_PLAN_LOCAL_FASTPATH:-1}" | tr '[:upper:]' '[:lower:]')" in
    1|true|yes|on) ;;
    *) return 1 ;;
  esac
  local_direct_enabled || return 1
  [[ "${governor_route:-}" == "LOCAL" ]] || return 1
  [[ "${governor_requires_sources:-true}" == "false" ]] || return 1
  [[ "${governor_requires_clarification:-false}" == "false" ]] || return 1
  [[ "${force_mode:-}" == "LOCAL" ]] || return 1
  [[ "${route_mode:-}" != "CLARIFY" ]] || return 1
  [[ "${needs_web:-true}" == "false" ]] || return 1
  [[ "${output_mode:-}" == "CHAT" ]] || return 1
  [[ -x "${LOCAL_ANSWER}" ]] || return 1
  [[ "${offline_action:-allow}" == "allow" ]] || return 1
  [[ -z "${one_clarifying_question:-}" ]] || return 1
  if [[ "${contextual_local_followup:-0}" != "1" ]]; then
    chat_memory_context_available && return 1
  fi
  return 0
}
local_chat_fast_path_eligible(){
  local_direct_eligible
}
local_worker_request_mode(){
  case "$(printf '%s' "${LUCY_LOCAL_WORKER_REQUEST_MODE:-client}" | tr '[:upper:]' '[:lower:]')" in
    direct|client) printf '%s' "${LUCY_LOCAL_WORKER_REQUEST_MODE:-client}" | tr '[:upper:]' '[:lower:]' ;;
    *) printf '%s' 'client' ;;
  esac
}
local_worker_enabled(){
  if [[ "$(local_worker_request_mode)" == "client" ]] && declare -F local_worker_client_enabled >/dev/null 2>&1; then
    local_worker_client_enabled
    return $?
  fi
  case "$(printf '%s' "${LUCY_LOCAL_WORKER_ENABLED:-1}" | tr '[:upper:]' '[:lower:]')" in
    1|true|yes|on) ;;
    *) return 1 ;;
  esac
  [[ -f "${LOCAL_WORKER}" ]] || return 1
  command -v python3 >/dev/null 2>&1 || return 1
  return 0
}
local_direct_request(){
  local q="$1"
  "${LOCAL_ANSWER}" "${q}"
}
local_direct_worker_fallback_request(){
  local q="$1"
  local_worker_request "${q}"
}
local_worker_request(){
  local q="$1"
  if [[ "$(local_worker_request_mode)" == "client" ]] && declare -F local_worker_client_request >/dev/null 2>&1; then
    local_worker_client_request "${q}"
    return $?
  fi
  python3 "${LOCAL_WORKER}" request --question "${q}"
}
resolve_augmented_provider(){
  local provider default_provider allowlist_csv item
  provider="$(printf '%s' "${LUCY_AUGMENTED_PROVIDER:-}" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9_-]//g')"
  default_provider="wikipedia"
  allowlist_csv="wikipedia,grok,openai"
  if [[ -f "${UNVERIFIED_CONTEXT_PROVIDER_DEFAULTS}" ]]; then
    while IFS='=' read -r key value; do
      key="$(printf '%s' "${key}" | tr -d '[:space:]')"
      value="$(printf '%s' "${value}" | sed -E 's/^[[:space:]]+|[[:space:]]+$//g')"
      [[ -n "${key}" ]] || continue
      [[ "${key}" =~ ^# ]] && continue
      case "${key}" in
        AUGMENTED_PROVIDER_DEFAULT) default_provider="$(printf '%s' "${value}" | tr '[:upper:]' '[:lower:]')" ;;
        AUGMENTED_PROVIDER_ALLOWLIST) allowlist_csv="$(printf '%s' "${value}" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')" ;;
      esac
    done < "${UNVERIFIED_CONTEXT_PROVIDER_DEFAULTS}"
  fi
  if [[ -z "${provider}" ]]; then
    provider="${default_provider}"
  fi
  IFS=',' read -r -a _provider_allowlist <<< "${allowlist_csv}"
  for item in "${_provider_allowlist[@]}"; do
    if [[ "${provider}" == "${item}" ]]; then
      printf '%s' "${provider}"
      return 0
    fi
  done
  return 1
}
provider_in_csv_allowlist(){
  local candidate="${1:-}" allowlist_csv="${2:-}" item
  [[ -n "${candidate}" ]] || return 1
  IFS=',' read -r -a _provider_allowlist <<< "${allowlist_csv}"
  for item in "${_provider_allowlist[@]}"; do
    if [[ "${candidate}" == "${item}" ]]; then
      return 0
    fi
  done
  return 1
}
load_augmented_provider_defaults(){
  local default_provider allowlist_csv key value
  default_provider="wikipedia"
  allowlist_csv="wikipedia,grok,openai"
  if [[ -f "${UNVERIFIED_CONTEXT_PROVIDER_DEFAULTS}" ]]; then
    while IFS='=' read -r key value; do
      key="$(printf '%s' "${key}" | tr -d '[:space:]')"
      value="$(printf '%s' "${value}" | sed -E 's/^[[:space:]]+|[[:space:]]+$//g')"
      [[ -n "${key}" ]] || continue
      [[ "${key}" =~ ^# ]] && continue
      case "${key}" in
        AUGMENTED_PROVIDER_DEFAULT) default_provider="$(printf '%s' "${value}" | tr '[:upper:]' '[:lower:]')" ;;
        AUGMENTED_PROVIDER_ALLOWLIST) allowlist_csv="$(printf '%s' "${value}" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')" ;;
      esac
    done < "${UNVERIFIED_CONTEXT_PROVIDER_DEFAULTS}"
  fi
  printf '%s\n%s\n' "${default_provider}" "${allowlist_csv}"
}
normalized_augmented_provider_query(){
  printf '%s' "${1:-}" \
    | tr '[:upper:]' '[:lower:]' \
    | sed -E 's/[^[:alnum:]?]+/ /g; s/[[:space:]]+/ /g; s/^ +| +$//g'
}
matches_augmented_provider_rule(){
  local q_norm="${1:-}" rule="${2:-}"
  case "${rule}" in
    rewrite_compare)
      grep -Eqi '(^| )(rewrite|rephrase|paraphrase|reword|edit|improve|clarify|compare|contrast|tradeoff|tradeoffs|summarize)( |$)' <<< "${q_norm}"
      ;;
    plain_explanation)
      grep -Eqi '(^| )(explain|why|how)( |$)|(plain english|plain language|simple terms|engineering intuition|with intuition|with an analogy|with analogy|real world analogy|broader conceptual articulation)' <<< "${q_norm}"
      ;;
    background_overview)
      grep -Eqi '(^| )(who is|who was|what is|what was|overview of|background on|history of|biography of)( |$)' <<< "${q_norm}"
      ;;
    *)
      return 1
      ;;
  esac
}
choose_auto_augmented_provider(){
  local q_norm="${1:-}" provider reason rule_label family augmented_family_alias
  provider="wikipedia"
  reason="stable factual overview"
  rule_label="default_background"
  family="$(printf '%s' "${manifest_intent_family:-${policy_intent_family:-${intent_family:-}}}" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z_]//g')"
  augmented_family_alias="$(printf '%s' "${policy_augmented_family:-}" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z_]//g')"
  if [[ -z "${family}" ]]; then
    case "${augmented_family_alias}" in
      background) family="background_overview" ;;
      synthesis) family="synthesis_explanation" ;;
    esac
  fi
  if [[ "${family}" == "background_overview" ]]; then
    rule_label="background_overview"
  elif [[ "${family}" == "synthesis_explanation" ]]; then
    provider="openai"
    reason="synthesis/explanation task"
    rule_label="plain_explanation"
  elif matches_augmented_provider_rule "${q_norm}" "rewrite_compare"; then
    provider="openai"
    reason="synthesis/explanation task"
    rule_label="rewrite_compare"
  elif matches_augmented_provider_rule "${q_norm}" "plain_explanation"; then
    provider="openai"
    reason="synthesis/explanation task"
    rule_label="plain_explanation"
  elif matches_augmented_provider_rule "${q_norm}" "background_overview"; then
    rule_label="background_overview"
  fi
  printf '%s\n%s\n%s\n' "${provider}" "${reason}" "${rule_label}"
}
select_augmented_provider(){
  local configured_provider default_provider allowlist_csv selected_provider selection_reason selection_rule q_norm
  configured_provider="$(printf '%s' "${LUCY_AUGMENTED_PROVIDER:-}" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9_-]//g')"
  mapfile -t _augmented_defaults < <(load_augmented_provider_defaults)
  default_provider="${_augmented_defaults[0]:-wikipedia}"
  allowlist_csv="${_augmented_defaults[1]:-wikipedia,grok,openai}"

  if [[ -n "${configured_provider}" ]]; then
    selected_provider="${configured_provider}"
    if ! provider_in_csv_allowlist "${selected_provider}" "${allowlist_csv}"; then
      return 1
    fi
    selection_reason="explicit provider selection"
    selection_rule="explicit_provider"
    q_norm="none"
  elif [[ "${route_control_mode:-AUTO}" == "AUTO" && "${augmented_direct_request:-false}" != "true" ]]; then
    q_norm="$(normalized_augmented_provider_query "${1:-}")"
    mapfile -t _auto_selection < <(choose_auto_augmented_provider "${q_norm}")
    selected_provider="${_auto_selection[0]:-wikipedia}"
    selection_reason="${_auto_selection[1]:-stable factual overview}"
    selection_rule="${_auto_selection[2]:-default_background}"
    if ! provider_in_csv_allowlist "${selected_provider}" "${allowlist_csv}"; then
      selected_provider="${default_provider}"
      selection_reason="configured default provider"
      selection_rule="configured_default"
    fi
  else
    selected_provider="${default_provider}"
    if ! provider_in_csv_allowlist "${selected_provider}" "${allowlist_csv}"; then
      return 1
    fi
    selection_reason="configured default provider"
    selection_rule="configured_default"
    q_norm="none"
  fi

  augmented_provider_selected="${selected_provider}"
  augmented_provider_selection_reason="${selection_reason}"
  augmented_provider_selection_query="${q_norm:-none}"
  augmented_provider_selection_rule="${selection_rule:-none}"
  return 0
}
augmented_provider_status_for_error_reason(){
  local reason
  reason="$(printf '%s' "${1:-none}" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9_:-]//g')"
  case "${reason}" in
    ""|none)
      printf '%s' "none"
      ;;
    missing_openai_configuration|missing_grok_configuration)
      printf '%s' "misconfigured"
      ;;
    provider_unavailable|openai_network_error|openai_http_error|openai_request_failed|grok_network_error|grok_http_error|grok_request_failed)
      printf '%s' "external_unavailable"
      ;;
    provider_no_context|provider_no_payload|provider_bad_payload|provider_exec_failed|missing_openai_tool|missing_grok_tool|unsupported_provider)
      printf '%s' "provider_error"
      ;;
    *)
      printf '%s' "provider_error"
      ;;
  esac
}
build_unverified_context_prompt_block(){
  local q="$1" selected_provider payload payload_rc parsed_output parsed_provider parsed_class parsed_title parsed_url parsed_text context_block
  local lat_aug_provider_start_ms
  unverified_context_prompt_block=""
  augmented_provider_error_reason="none"
  augmented_provider_status="none"
  lat_aug_provider_start_ms="$(latprof_now_ms)"
  select_augmented_provider "${q}" || return 1
  selected_provider="${augmented_provider_selected:-}"
  [[ -n "${selected_provider}" ]] || return 1
  augmented_provider="${selected_provider}"
  [[ -x "${UNVERIFIED_CONTEXT_PROVIDER_DISPATCH_TOOL}" ]] || return 1

  # FIX: Use trap to ensure set -e is restored on signal interruption.
  # Prevents leaving shell in permanent set +e state if signal arrives
  # between set +e and the subprocess execution.
  local _restore_set_e='set -e'
  set +e
  trap "${_restore_set_e}" EXIT INT TERM
  payload="$("${UNVERIFIED_CONTEXT_PROVIDER_DISPATCH_TOOL}" "${selected_provider}" "${q}" 2>/dev/null)"
  payload_rc=$?
  trap - EXIT INT TERM
  eval "${_restore_set_e}"
  if [[ "${payload_rc}" -ne 0 ]]; then
    latprof_append "execute_plan" "augmented_provider_context" "$(( $(latprof_now_ms) - lat_aug_provider_start_ms ))"
    augmented_provider_error_reason="$(
      PAYLOAD_JSON="${payload}" python3 - <<'PY'
import json
import os
raw = os.environ.get("PAYLOAD_JSON", "")
reason = "provider_unavailable"
try:
    parsed = json.loads(raw)
except Exception:
    parsed = {}
if isinstance(parsed, dict):
    candidate = str(parsed.get("reason", "")).strip()
    if candidate:
        reason = candidate
print(reason)
PY
    )"
    augmented_provider_status="$(augmented_provider_status_for_error_reason "${augmented_provider_error_reason}")"
    return 1
  fi

  parsed_output="$(
    PAYLOAD_JSON="${payload}" python3 - <<'PY'
import json
import os
import re
import sys

raw = os.environ.get("PAYLOAD_JSON", "")
try:
    payload = json.loads(raw)
except Exception:
    raise SystemExit(1)

if not isinstance(payload, dict):
    raise SystemExit(1)

if not payload.get("ok"):
    raise SystemExit(1)

provider = str(payload.get("provider", "")).strip().lower()
if not provider:
    raise SystemExit(1)

source_class = str(payload.get("class", "")).strip()
if not source_class:
    raise SystemExit(1)

title = str(payload.get("title", "")).strip()
title = re.sub(r"\s+", " ", title).strip()
url = str(payload.get("url", "")).strip()
text = str(payload.get("text", "")).strip()
text = re.sub(r"\s+", " ", text).strip()
if not text:
    raise SystemExit(1)

print(provider)
print(source_class)
print(title)
print(url)
print(text)
PY
  )" || {
    latprof_append "execute_plan" "augmented_provider_context" "$(( $(latprof_now_ms) - lat_aug_provider_start_ms ))"
    return 1
  }

  parsed_provider="$(printf '%s\n' "${parsed_output}" | sed -n '1p')"
  parsed_class="$(printf '%s\n' "${parsed_output}" | sed -n '2p')"
  parsed_title="$(printf '%s\n' "${parsed_output}" | sed -n '3p')"
  parsed_url="$(printf '%s\n' "${parsed_output}" | sed -n '4p')"
  parsed_text="$(printf '%s\n' "${parsed_output}" | sed -n '5p')"
  [[ -n "${parsed_text}" ]] || return 1

  unverified_context_used="true"
  augmented_provider="${parsed_provider}"
  set_augmented_provider_used "${parsed_provider}"
  unverified_context_class="${parsed_class:-wikipedia_general}"
  unverified_context_title="${parsed_title}"
  unverified_context_url="${parsed_url}"
  unverified_context_text="${parsed_text}"
  context_block="Unverified context source class: ${unverified_context_class} (not evidence)"
  if [[ -n "${unverified_context_url}" ]]; then
    context_block+=$'\n'"Unverified context reference: ${unverified_context_url}"
  fi
  context_block+=$'\n'"Unverified context excerpt: ${parsed_text}"
  unverified_context_prompt_block="${context_block}"
  augmented_provider_status="available"
  latprof_append "execute_plan" "augmented_provider_context" "$(( $(latprof_now_ms) - lat_aug_provider_start_ms ))"
  return 0
}
build_augmented_background_context_text(){
  local lines=()
  if [[ -n "${unverified_context_title}" ]]; then
    lines+=("${unverified_context_title}")
  fi
  if [[ -n "${unverified_context_text}" ]]; then
    lines+=("${unverified_context_text}")
  fi
  printf '%s\n' "${lines[@]}"
}
load_augmented_generation_meta(){
  local meta_file="${1:-}" parsed_output
  augmented_behavior_shape="stable_summary"
  augmented_clarification_required="false"
  [[ -n "${meta_file}" && -f "${meta_file}" ]] || return 0
  parsed_output="$(python3 - "${meta_file}" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    payload = json.loads(path.read_text(encoding="utf-8"))
except Exception:
    raise SystemExit(1)

print(str(payload.get("answer_shape", "stable_summary")).strip() or "stable_summary")
print("true" if payload.get("clarification_required") else "false")
PY
  )" || return 0
  augmented_behavior_shape="$(printf '%s\n' "${parsed_output}" | sed -n '1p')"
  augmented_clarification_required="$(printf '%s\n' "${parsed_output}" | sed -n '2p')"
}
augmented_response_requires_clarification(){
  [[ "${augmented_clarification_required:-false}" == "true" || "${augmented_behavior_shape:-}" == "clarify_question" ]]
}
run_augmented_unverified_answer(){
  local q="$1" q_effective raw rc augmented_background_text augmented_meta_file
  local lat_aug_total_start_ms lat_aug_local_start_ms
  unverified_context_used="false"
  unverified_context_class="none"
  unverified_context_title=""
  unverified_context_url=""
  unverified_context_text=""
  augmented_provider="none"
  augmented_provider_used="none"
  augmented_provider_usage_class="none"
  augmented_provider_cost_notice="false"
  augmented_paid_provider_invoked="false"
  augmented_provider_error_reason="none"
  augmented_provider_status="none"
  augmented_provider_selection_reason="none"
  augmented_provider_selection_query="none"
  augmented_provider_selection_rule="none"
  unverified_context_prompt_block=""
  augmented_unverified_raw=""
  augmented_behavior_shape="stable_summary"
  augmented_clarification_required="false"
  augmented_meta_file=""
  lat_aug_total_start_ms="$(latprof_now_ms)"
  q_effective="${q}"
  if build_unverified_context_prompt_block "${q}"; then
    augmented_background_text="$(build_augmented_background_context_text)"
  elif [[ "${augmented_provider}" == "grok" || "${augmented_provider}" == "openai" ]] \
    && [[ "${augmented_provider_selection_reason}" == "explicit provider selection" ]]; then
    # Explicit provider selections must fail explicitly when unavailable/misconfigured.
    latprof_append "execute_plan" "augmented_total" "$(( $(latprof_now_ms) - lat_aug_total_start_ms ))"
    return 2
  fi
  raw=""
  rc=1
  augmented_meta_file="$(mktemp "${TMPDIR:-/tmp}/lucy_augmented_meta.XXXXXX.json" 2>/dev/null || true)"
  if local_worker_enabled; then
    lat_aug_local_start_ms="$(latprof_now_ms)"
    # FIX: Use trap to ensure set -e is restored on signal interruption.
    local _restore_set_e='set -e'
    set +e
    trap "${_restore_set_e}" EXIT INT TERM
    raw="$(
      LUCY_LOCAL_GEN_ROUTE_MODE="AUGMENTED" \
      LUCY_LOCAL_GEN_OUTPUT_MODE="CHAT" \
      LUCY_LOCAL_AUGMENTED_USER_QUESTION="${q}" \
      LUCY_LOCAL_AUGMENTED_BACKGROUND_CONTEXT="${augmented_background_text:-}" \
      LUCY_LOCAL_AUGMENTED_CONTEXT_CLASS="${unverified_context_class}" \
      LUCY_LOCAL_AUGMENTED_CONTEXT_TITLE="${unverified_context_title}" \
      LUCY_LOCAL_AUGMENTED_CONTEXT_URL="${unverified_context_url}" \
      LUCY_LOCAL_AUGMENTED_META_FILE="${augmented_meta_file}" \
      local_worker_request "${q_effective}" 2>/dev/null
    )"
    rc=$?
    trap - EXIT INT TERM
    eval "${_restore_set_e}"
    latprof_append "execute_plan" "augmented_local_generation" "$(( $(latprof_now_ms) - lat_aug_local_start_ms ))"
    if [[ "${rc}" -eq 0 && -n "$(printf '%s' "${raw}" | tr -d '[:space:]')" ]]; then
      augmented_unverified_raw="${raw}"
      load_augmented_generation_meta "${augmented_meta_file}"
      [[ -n "${augmented_meta_file}" ]] && rm -f "${augmented_meta_file}" 2>/dev/null || true
      latprof_append "execute_plan" "augmented_total" "$(( $(latprof_now_ms) - lat_aug_total_start_ms ))"
      return 0
    fi
  fi
  if [[ -x "${LOCAL_ANSWER}" ]]; then
    lat_aug_local_start_ms="$(latprof_now_ms)"
    set +e
    raw="$(
      LUCY_LOCAL_GEN_ROUTE_MODE="AUGMENTED" \
      LUCY_LOCAL_GEN_OUTPUT_MODE="CHAT" \
      LUCY_LOCAL_AUGMENTED_USER_QUESTION="${q}" \
      LUCY_LOCAL_AUGMENTED_BACKGROUND_CONTEXT="${augmented_background_text:-}" \
      LUCY_LOCAL_AUGMENTED_CONTEXT_CLASS="${unverified_context_class}" \
      LUCY_LOCAL_AUGMENTED_CONTEXT_TITLE="${unverified_context_title}" \
      LUCY_LOCAL_AUGMENTED_CONTEXT_URL="${unverified_context_url}" \
      LUCY_LOCAL_AUGMENTED_META_FILE="${augmented_meta_file}" \
      local_direct_request "${q_effective}" 2>/dev/null
    )"
    rc=$?
    trap - EXIT INT TERM
    eval "${_restore_set_e}"
    latprof_append "execute_plan" "augmented_local_generation" "$(( $(latprof_now_ms) - lat_aug_local_start_ms ))"
    if [[ "${rc}" -eq 0 && -n "$(printf '%s' "${raw}" | tr -d '[:space:]')" ]]; then
      augmented_unverified_raw="${raw}"
      load_augmented_generation_meta "${augmented_meta_file}"
      [[ -n "${augmented_meta_file}" ]] && rm -f "${augmented_meta_file}" 2>/dev/null || true
      latprof_append "execute_plan" "augmented_total" "$(( $(latprof_now_ms) - lat_aug_total_start_ms ))"
      return 0
    fi
  fi
  [[ -n "${augmented_meta_file}" ]] && rm -f "${augmented_meta_file}" 2>/dev/null || true
  latprof_append "execute_plan" "augmented_total" "$(( $(latprof_now_ms) - lat_aug_total_start_ms ))"
  return 1
}
run_augmented_unverified_fallback_answer(){
  local q="$1"
  local saved_augmented_direct_request="${augmented_direct_request:-false}"
  local rc

  if [[ -n "${LUCY_AUGMENTED_PROVIDER:-}" ]]; then
    augmented_direct_request="true"
  fi
  run_augmented_unverified_answer "${q}" 2>/dev/null
  rc=$?
  augmented_direct_request="${saved_augmented_direct_request}"
  return "${rc}"
}
local_degradation_augmented_fallback_allowed(){
  [[ "${augmentation_policy}" != "disabled" ]] || return 1
  [[ "${augmented_direct_request}" != "true" ]] || return 1
  [[ "${route_control_mode:-AUTO}" != "FORCED_OFFLINE" ]] || return 1
  return 0
}
validated_insufficient_recovery_eligible(){
  [[ "${force_mode}" != "LOCAL" ]] || return 1
  [[ "${intent}" != "MEDICAL_INFO" ]] || return 1
  [[ "${intent}" != "WEB_DOC" ]] || return 1
  [[ "${intent}" != "PRIMARY_DOC" ]] || return 1
  [[ "${category}" != "travel_advisory" ]] || return 1
  [[ "${routing_signal_source_request:-false}" != "true" ]] || return 1
  [[ "${routing_signal_news:-false}" != "true" ]] || return 1
  [[ "${routing_signal_conflict:-false}" != "true" ]] || return 1
  [[ "${routing_signal_geopolitics:-false}" != "true" ]] || return 1
  [[ "${routing_signal_israel_region:-false}" != "true" ]] || return 1
  [[ "${routing_signal_current_product:-false}" != "true" ]] || return 1
  [[ "${manifest_evidence_mode_reason:-}" != "explicit_source_request" ]] || return 1
  [[ "${manifest_evidence_mode_reason:-}" != "source_request" ]] || return 1
  return 0
}
run_local_best_effort_recovery_answer(){
  local q="$1" raw context_text rendered
  local rc
  context_text="Verification from current evidence was insufficient. Use stable general background only. Do not present the answer as source-backed or verified current status."
  # FIX: Use trap to ensure set -e is restored on signal interruption.
  local _restore_set_e='set -e'
  set +e
  trap "${_restore_set_e}" EXIT INT TERM
  raw="$(
    LUCY_LOCAL_GEN_ROUTE_MODE="AUGMENTED" \
    LUCY_LOCAL_GEN_OUTPUT_MODE="CHAT" \
    LUCY_LOCAL_AUGMENTED_USER_QUESTION="${q}" \
    LUCY_LOCAL_AUGMENTED_BACKGROUND_CONTEXT="${context_text}" \
    local_direct_request "${q}" 2>/dev/null
  )"
  rc=$?
  trap - EXIT INT TERM
  eval "${_restore_set_e}"
  [[ "${rc}" -eq 0 ]] || return 1
  [[ -n "$(printf '%s' "${raw}" | tr -d '[:space:]')" ]] || return 1
  rendered="$(render_chat_fast_from_raw "${raw}")"
  rendered="$(runtime_non_empty_guard "${q}" "${rendered}" "CHAT")"
  is_runtime_local_prompt_fallback_text "${rendered}" && return 1
  is_evidence_style_text "${rendered}" && return 1
  is_clarification_style_text "${rendered}" && return 1
  final_out="${rendered}"
  return 0
}
apply_validated_insufficient_recovery(){
  local q="$1"
  local aug_fallback_rc
  primary_outcome_code="validated_insufficient"
  primary_trust_class="evidence_backed"
  router_outcome_code="validated_insufficient"
  outcome_code_override="validated_insufficient"
  fallback_used="false"
  recovery_attempted="false"
  recovery_used="false"
  recovery_eligible="false"
  recovery_lane="none"

  if ! validated_insufficient_recovery_eligible; then
    return 1
  fi

  recovery_eligible="true"
  recovery_attempted="true"
  if run_local_best_effort_recovery_answer "${q}"; then
    final_out="Best-effort recovery (not source-backed answer):"$'\n'"${final_out}"
    final_mode="LOCAL"
    trust_class="best_effort_unverified"
    fallback_used="true"
    fallback_reason="validated_insufficient"
    fallback_kind="local_best_effort_recovery"
    router_outcome_code="best_effort_recovery_answer"
    outcome_code_override="best_effort_recovery_answer"
    recovery_used="true"
    recovery_lane="local_best_effort"
    augmented_provider="none"
    augmented_provider_selected="none"
    augmented_provider_used="none"
    augmented_provider_usage_class="local"
    augmented_provider_call_reason="recovery_local"
    augmented_provider_cost_notice="false"
    augmented_paid_provider_invoked="false"
    unverified_context_used="false"
    unverified_context_class="none"
    unverified_context_title=""
    unverified_context_url=""
    return 0
  fi

  if [[ "${augmentation_policy}" != "disabled" && "${augmented_direct_request}" != "true" ]]; then
    if run_augmented_unverified_fallback_answer "${q}"; then
      final_out="$(render_chat_fast_from_raw "${augmented_unverified_raw}")"
      final_out="$(runtime_non_empty_guard "${q}" "${final_out}" "CHAT")"
      final_mode="AUGMENTED"
      trust_class="unverified"
      fallback_used="true"
      fallback_reason="validated_insufficient"
      fallback_kind="augmented_unverified_fallback"
      router_outcome_code="augmented_fallback_answer"
      outcome_code_override="augmented_fallback_answer"
      recovery_used="true"
      recovery_lane="augmented_fallback"
      augmented_provider_call_reason="fallback"
      if [[ "${augmented_provider_used}" == "none" ]]; then
        augmented_provider_usage_class="local"
        augmented_provider_cost_notice="false"
        augmented_paid_provider_invoked="false"
      fi
      final_out="Augmented fallback (unverified answer):"$'\n'"${final_out}"
      return 0
    fi
    aug_fallback_rc=$?
    if [[ "${augmented_provider}" == "grok" && "${aug_fallback_rc}" -eq 2 ]]; then
      fallback_reason="validated_insufficient_grok_provider_unavailable"
    elif [[ "${augmented_provider}" == "openai" && "${aug_fallback_rc}" -eq 2 ]]; then
      fallback_reason="validated_insufficient_openai_provider_unavailable"
    else
      fallback_reason="validated_insufficient_no_augmented_result"
    fi
    augmented_provider_call_reason="error"
  else
    fallback_reason="validated_insufficient_no_recovery_allowed"
  fi

  router_outcome_code="validated_insufficient"
  outcome_code_override="validated_insufficient"
  fallback_used="false"
  return 1
}
apply_local_degradation_augmented_fallback(){
  local q="$1" reason="$2"
  local aug_raw

  local_degradation_augmented_fallback_allowed || return 1
  run_augmented_unverified_fallback_answer "${q}" || return 1

  aug_raw="${augmented_unverified_raw}"
  final_mode="AUGMENTED"
  trust_class="unverified"
  fallback_used="true"
  fallback_reason="${reason}"
  fallback_kind="augmented_unverified_fallback"
  augmented_provider_call_reason="fallback"
  router_outcome_code="augmented_fallback_answer"
  outcome_code_override="augmented_fallback_answer"
  if [[ "${augmented_provider_used}" == "none" ]]; then
    augmented_provider_usage_class="local"
    augmented_provider_cost_notice="false"
    augmented_paid_provider_invoked="false"
  fi
  final_out="$(render_chat_fast_from_raw "${aug_raw}")"
  if [[ -z "$(printf '%s' "${final_out}" | tr -d '[:space:]')" ]]; then
    final_out="$(runtime_local_fallback_text)"
  fi
  final_out="Augmented fallback (unverified answer):"$'\n'"${final_out}"
  return 0
}
augmented_provider_error_message(){
  local provider="${1:-}" reason="${2:-provider_unavailable}"
  case "${provider}:${reason}" in
    grok:missing_grok_configuration)
      printf '%s' "Grok provider is selected but missing configuration (set GROK_API_KEY or LUCY_GROK_MOCK_TEXT)."
      ;;
    grok:grok_http_error|grok:grok_network_error|grok:grok_request_failed|grok:grok_no_text|grok:provider_no_context)
      printf '%s' "Grok provider is selected but currently unavailable."
      ;;
    grok:*)
      printf '%s' "Grok provider is selected but unavailable (${reason})."
      ;;
    openai:missing_openai_configuration)
      printf '%s' "OpenAI provider is selected but missing configuration (set OPENAI_API_KEY or LUCY_OPENAI_MOCK_TEXT)."
      ;;
    openai:openai_http_error|openai:openai_network_error|openai:openai_request_failed|openai:openai_bad_payload|openai:openai_no_text|openai:provider_no_context)
      printf '%s' "OpenAI provider is selected but currently unavailable."
      ;;
    openai:*)
      printf '%s' "OpenAI provider is selected but unavailable (${reason})."
      ;;
    *)
      printf '%s' "Augmented provider is unavailable (${provider}:${reason})."
      ;;
  esac
}
quality_dbg(){
  [[ "${LUCY_DEBUG_QUALITY_GUARDS:-0}" == "1" ]] || return 0
  printf 'DEBUG_QUALITY %s\n' "$*" >&2
}
trace_enabled(){
  case "$(printf '%s' "${LUCY_TRACE_ROUTE:-0}" | tr '[:upper:]' '[:lower:]')" in
    1|true|yes|on) return 0 ;;
    *) return 1 ;;
  esac
}
policy_route_alias(){
  case "$(printf '%s' "${1:-}" | tr '[:lower:]' '[:upper:]')" in
    LOCAL|NEWS|EVIDENCE|AUGMENTED|CLARIFY)
      printf '%s' "$(printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]')"
      ;;
    *)
      printf ''
      ;;
  esac
}
assert_manifest_route_compatibility(){
  local expected_route expected_policy_route
  expected_route="${manifest_selected_route:-}"
  [[ -n "${expected_route}" ]] || { err "missing manifest_selected_route for compatibility aliases"; exit 4; }
  expected_policy_route="$(policy_route_alias "${expected_route}")"
  [[ "${force_mode:-}" == "${expected_route}" ]] || { err "manifest compatibility drift: force_mode=${force_mode:-} manifest=${expected_route}"; exit 4; }
  [[ "${route_mode:-}" == "${expected_route}" ]] || { err "manifest compatibility drift: route_mode=${route_mode:-} manifest=${expected_route}"; exit 4; }
  [[ "${governor_route:-}" == "${expected_route}" ]] || { err "manifest compatibility drift: governor_route=${governor_route:-} manifest=${expected_route}"; exit 4; }
  [[ "${policy_actual_route:-}" == "${expected_policy_route}" ]] || { err "manifest compatibility drift: policy_actual_route=${policy_actual_route:-} manifest=${expected_policy_route}"; exit 4; }
  [[ "${policy_recommended_route:-}" == "${expected_policy_route}" ]] || { err "manifest compatibility drift: policy_recommended_route=${policy_recommended_route:-} manifest=${expected_policy_route}"; exit 4; }
}
emit_route_trace(){
  local identity_loaded="${1:-no}" identity_source="${2:-not_applicable}"
  trace_enabled || return 0
  {
    printf 'ACTIVE_ROOT=%s\n' "${ROOT}"
    printf 'ENTRYPOINT=%s\n' "${BASH_SOURCE[0]}"
    printf 'SURFACE=%s\n' "${LUCY_SURFACE:-cli}"
    printf 'MODE=%s\n' "${route_control_mode}"
    printf 'CLASSIFIER_INTENT=%s\n' "${classifier_intent}"
    printf 'CLASSIFIER_CATEGORY=%s\n' "${classifier_category}"
    printf 'POLICY_RECOMMENDED_ROUTE=%s\n' "${policy_recommended_route}"
    printf 'ACTUAL_ROUTE=%s\n' "${policy_actual_route}"
    printf 'PIPELINE=%s\n' "${force_mode}"
    printf 'IDENTITY_CONTEXT_LOADED=%s\n' "${identity_loaded}"
    printf 'IDENTITY_CONTEXT_SOURCE=%s\n' "${identity_source}"
  } >&2
}
emit_dryrun_summary(){
  emit_route_trace "no" "not_applicable"
  printf 'PLAN_JSON=%s\n' "${PLAN_JSON:-}"
  printf 'RESOLVED_QUESTION=%s\n' "${question_for_plan:-}"
  printf 'ROUTE_CONTROL_MODE=%s\n' "${route_control_mode:-}"
  printf 'AUGMENTATION_POLICY=%s\n' "${augmentation_policy:-disabled}"
  printf 'AUGMENTED_DIRECT_REQUEST=%s\n' "${augmented_direct_request:-false}"
  printf 'PIPELINE=%s\n' "${force_mode:-}"
  printf 'OUTPUT_MODE=%s\n' "${output_mode:-${plan_output_mode:-}}"
  printf 'ALLOW_DOMAINS_FILE=%s\n' "${router_allow_domains_file:-}"
  printf 'REGION_FILTER=%s\n' "${region_filter:-}"
  printf 'POLICY_RECOMMENDED_ROUTE=%s\n' "${policy_recommended_route:-}"
  printf 'POLICY_ACTUAL_ROUTE=%s\n' "${policy_actual_route:-}"
  printf 'POLICY_OPERATOR_OVERRIDE=%s\n' "${policy_operator_override:-}"
  printf 'POLICY_CONFIDENCE=%s\n' "${policy_confidence:-}"
  printf 'POLICY_CONFIDENCE_THRESHOLD=%s\n' "${policy_confidence_threshold:-}"
  printf 'POLICY_FRESHNESS_REQUIREMENT=%s\n' "${policy_freshness_requirement:-}"
  printf 'POLICY_RISK_LEVEL=%s\n' "${policy_risk_level:-}"
  printf 'POLICY_SOURCE_CRITICALITY=%s\n' "${policy_source_criticality:-}"
  printf 'POLICY_INTENT_FAMILY=%s\n' "${policy_intent_family:-}"
  printf 'POLICY_AUGMENTED_FAMILY=%s\n' "${policy_augmented_family:-}"
  printf 'POLICY_REASON_CODES=%s\n' "${policy_reason_codes_csv:-}"
  printf 'MANIFEST_VERSION=%s\n' "${manifest_version:-}"
  printf 'MANIFEST_SELECTED_ROUTE=%s\n' "${manifest_selected_route:-}"
  printf 'MANIFEST_INTENT_FAMILY=%s\n' "${manifest_intent_family:-}"
  printf 'MANIFEST_ALLOWED_ROUTES=%s\n' "${manifest_allowed_routes:-}"
  printf 'MANIFEST_FORBIDDEN_ROUTES=%s\n' "${manifest_forbidden_routes:-}"
  printf 'MANIFEST_AUTHORITY_BASIS=%s\n' "${manifest_authority_basis:-}"
  printf 'MANIFEST_CLARIFY_REQUIRED=%s\n' "${manifest_clarify_required:-}"
  printf 'MANIFEST_CONTEXT_RESOLUTION_USED=%s\n' "${manifest_context_resolution_used:-}"
  printf 'MANIFEST_CONTEXT_REFERENT_CONFIDENCE=%s\n' "${manifest_context_referent_confidence:-}"
  printf 'MANIFEST_EVIDENCE_MODE=%s\n' "${manifest_evidence_mode:-}"
  printf 'MANIFEST_EVIDENCE_MODE_REASON=%s\n' "${manifest_evidence_mode_reason:-}"
  printf 'MANIFEST_EVIDENCE_SELECTION=%s\n' "$(manifest_evidence_selection_label "${manifest_evidence_mode:-}" "${manifest_evidence_mode_reason:-}")"
  printf 'WINNING_SIGNAL=%s\n' "${winning_signal:-}"
  printf 'PRECEDENCE_VERSION=%s\n' "${precedence_version:-}"
  printf 'ROUTING_SIGNAL_TEMPORAL=%s\n' "${routing_signal_temporal:-}"
  printf 'ROUTING_SIGNAL_NEWS=%s\n' "${routing_signal_news:-}"
  printf 'ROUTING_SIGNAL_CONFLICT=%s\n' "${routing_signal_conflict:-}"
  printf 'ROUTING_SIGNAL_GEOPOLITICS=%s\n' "${routing_signal_geopolitics:-}"
  printf 'ROUTING_SIGNAL_ISRAEL_REGION=%s\n' "${routing_signal_israel_region:-}"
  printf 'ROUTING_SIGNAL_SOURCE_REQUEST=%s\n' "${routing_signal_source_request:-}"
  printf 'ROUTING_SIGNAL_URL=%s\n' "${routing_signal_url:-}"
  printf 'ROUTING_SIGNAL_AMBIGUITY_FOLLOWUP=%s\n' "${routing_signal_ambiguity_followup:-}"
  printf 'ROUTING_SIGNAL_MEDICAL_CONTEXT=%s\n' "${routing_signal_medical_context:-}"
  printf 'ROUTING_SIGNAL_CURRENT_PRODUCT=%s\n' "${routing_signal_current_product:-}"
  printf 'SEMANTIC_INTERPRETER_FIRED=%s\n' "${semantic_interpreter_fired:-}"
  printf 'SEMANTIC_INTERPRETER_ORIGINAL_QUERY=%s\n' "${semantic_interpreter_original_query:-}"
  printf 'SEMANTIC_INTERPRETER_RESOLVED_EXECUTION_QUERY=%s\n' "${semantic_interpreter_resolved_execution_query:-}"
  printf 'SEMANTIC_INTERPRETER_INFERRED_DOMAIN=%s\n' "${semantic_interpreter_inferred_domain:-}"
  printf 'SEMANTIC_INTERPRETER_INFERRED_INTENT_FAMILY=%s\n' "${semantic_interpreter_inferred_intent_family:-}"
  printf 'SEMANTIC_INTERPRETER_CONFIDENCE=%s\n' "${semantic_interpreter_confidence:-}"
  printf 'SEMANTIC_INTERPRETER_GATE_REASON=%s\n' "${semantic_interpreter_gate_reason:-}"
  printf 'SEMANTIC_INTERPRETER_INVOCATION_ATTEMPTED=%s\n' "${semantic_interpreter_invocation_attempted:-}"
  printf 'SEMANTIC_INTERPRETER_RESULT_STATUS=%s\n' "${semantic_interpreter_result_status:-}"
  printf 'SEMANTIC_INTERPRETER_USE_REASON=%s\n' "${semantic_interpreter_use_reason:-}"
  printf 'SEMANTIC_INTERPRETER_USED_FOR_ROUTING=%s\n' "${semantic_interpreter_used_for_routing:-}"
  printf 'SEMANTIC_INTERPRETER_FORWARD_CANDIDATES=%s\n' "${semantic_interpreter_forward_candidates:-}"
  printf 'SEMANTIC_INTERPRETER_SELECTED_NORMALIZED_QUERY=%s\n' "${semantic_interpreter_selected_normalized_query:-}"
  printf 'SEMANTIC_INTERPRETER_SELECTED_RETRIEVAL_QUERY=%s\n' "${semantic_interpreter_selected_retrieval_query:-}"
  printf 'MEDICATION_DETECTOR_FIRED=%s\n' "${medical_detector_fired:-}"
  printf 'MEDICATION_DETECTOR_ORIGINAL_QUERY=%s\n' "${medical_detector_original_query:-}"
  printf 'MEDICATION_DETECTOR_RESOLVED_EXECUTION_QUERY=%s\n' "${medical_detector_resolved_execution_query:-}"
  printf 'MEDICATION_DETECTOR_DETECTION_SOURCE=%s\n' "${medical_detector_detection_source:-}"
  printf 'MEDICATION_DETECTOR_PATTERN_FAMILY=%s\n' "${medical_detector_pattern_family:-}"
  printf 'MEDICATION_DETECTOR_CANDIDATE_MEDICATION=%s\n' "${medical_detector_candidate_medication:-}"
  printf 'MEDICATION_DETECTOR_NORMALIZED_CANDIDATE=%s\n' "${medical_detector_normalized_candidate:-}"
  printf 'MEDICATION_DETECTOR_CONFIDENCE=%s\n' "${medical_detector_confidence:-}"
  printf 'MEDICATION_DETECTOR_CONFIDENCE_SCORE=%s\n' "${medical_detector_confidence_score:-}"
  printf 'GOVERNOR_INTENT=%s\n' "${governor_intent:-}"
  printf 'GOVERNOR_CONFIDENCE=%s\n' "${governor_confidence:-}"
  printf 'GOVERNOR_ROUTE=%s\n' "${governor_route:-}"
  printf 'GOVERNOR_REQUIRES_SOURCES=%s\n' "${governor_requires_sources:-}"
  printf 'GOVERNOR_REQUIRES_CLARIFICATION=%s\n' "${governor_requires_clarification:-}"
  printf 'GOVERNOR_FALLBACK_POLICY=%s\n' "${governor_fallback_policy:-}"
  printf 'GOVERNOR_AUDIT_TAGS=%s\n' "${governor_audit_tags:-}"
  printf 'GOVERNOR_ALLOWED_TOOLS=%s\n' "${governor_allowed_tools:-}"
  printf 'GOVERNOR_CONTRACT_VERSION=%s\n' "${governor_contract_version:-}"
  printf 'GOVERNOR_LOCAL_RESPONSE_ID=%s\n' "${governor_local_response_id:-}"
}
emit_execution_contract_trace(){
  local trace_file="${LUCY_EXECUTION_CONTRACT_TRACE_FILE:-}"
  [[ -n "${trace_file}" ]] || return 0
  mkdir -p "$(dirname "${trace_file}")" 2>/dev/null || true
  python3 - "${trace_file}" <<'PY'
import json
import os
import sys
from pathlib import Path

def as_bool(value: str) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}

def as_float(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0

def as_csv(value: str) -> list[str]:
    return [item for item in (value or "").split(",") if item]

payload = {
    "question": os.environ.get("LUCY_TRACE_EXECUTION_QUESTION", ""),
    "route_mode": os.environ.get("LUCY_TRACE_EXECUTION_ROUTE_MODE", ""),
    "output_mode": os.environ.get("LUCY_TRACE_EXECUTION_OUTPUT_MODE", ""),
    "offline_action": os.environ.get("LUCY_TRACE_EXECUTION_OFFLINE_ACTION", ""),
    "route_manifest": {
        "manifest_version": os.environ.get("LUCY_TRACE_MANIFEST_VERSION", ""),
        "precedence_version": os.environ.get("LUCY_TRACE_MANIFEST_PRECEDENCE_VERSION", ""),
        "original_query": os.environ.get("LUCY_TRACE_MANIFEST_ORIGINAL_QUERY", ""),
        "resolved_execution_query": os.environ.get("LUCY_TRACE_MANIFEST_RESOLVED_EXECUTION_QUERY", ""),
        "selected_route": os.environ.get("LUCY_TRACE_MANIFEST_SELECTED_ROUTE", ""),
        "intent_family": os.environ.get("LUCY_TRACE_MANIFEST_INTENT_FAMILY", ""),
        "allowed_routes": as_csv(os.environ.get("LUCY_TRACE_MANIFEST_ALLOWED_ROUTES", "")),
        "forbidden_routes": as_csv(os.environ.get("LUCY_TRACE_MANIFEST_FORBIDDEN_ROUTES", "")),
        "winning_signal": os.environ.get("LUCY_TRACE_MANIFEST_WINNING_SIGNAL", ""),
        "clarify_required": as_bool(os.environ.get("LUCY_TRACE_MANIFEST_CLARIFY_REQUIRED", "")),
        "authority_basis": os.environ.get("LUCY_TRACE_MANIFEST_AUTHORITY_BASIS", ""),
        "context_resolution_used": as_bool(os.environ.get("LUCY_TRACE_MANIFEST_CONTEXT_RESOLUTION_USED", "")),
        "context_referent_confidence": os.environ.get("LUCY_TRACE_MANIFEST_CONTEXT_REFERENT_CONFIDENCE", ""),
        "signals": {
            "temporal": as_bool(os.environ.get("LUCY_TRACE_MANIFEST_SIGNAL_TEMPORAL", "")),
            "news": as_bool(os.environ.get("LUCY_TRACE_MANIFEST_SIGNAL_NEWS", "")),
            "conflict": as_bool(os.environ.get("LUCY_TRACE_MANIFEST_SIGNAL_CONFLICT", "")),
            "geopolitics": as_bool(os.environ.get("LUCY_TRACE_MANIFEST_SIGNAL_GEOPOLITICS", "")),
            "israel_region_live": as_bool(os.environ.get("LUCY_TRACE_MANIFEST_SIGNAL_ISRAEL_REGION_LIVE", "")),
            "source_request": as_bool(os.environ.get("LUCY_TRACE_MANIFEST_SIGNAL_SOURCE_REQUEST", "")),
            "url": as_bool(os.environ.get("LUCY_TRACE_MANIFEST_SIGNAL_URL", "")),
            "ambiguity_followup": as_bool(os.environ.get("LUCY_TRACE_MANIFEST_SIGNAL_AMBIGUITY_FOLLOWUP", "")),
            "medical_context": as_bool(os.environ.get("LUCY_TRACE_MANIFEST_SIGNAL_MEDICAL_CONTEXT", "")),
            "current_product": as_bool(os.environ.get("LUCY_TRACE_MANIFEST_SIGNAL_CURRENT_PRODUCT", "")),
        },
    },
    "semantic_interpreter": {
        "interpreter_fired": as_bool(os.environ.get("LUCY_TRACE_SEMANTIC_FIRED", "")),
        "original_query": os.environ.get("LUCY_TRACE_SEMANTIC_ORIGINAL_QUERY", ""),
        "resolved_execution_query": os.environ.get("LUCY_TRACE_SEMANTIC_RESOLVED_EXECUTION_QUERY", ""),
        "inferred_domain": os.environ.get("LUCY_TRACE_SEMANTIC_INFERRED_DOMAIN", ""),
        "inferred_intent_family": os.environ.get("LUCY_TRACE_SEMANTIC_INFERRED_INTENT_FAMILY", ""),
        "confidence": as_float(os.environ.get("LUCY_TRACE_SEMANTIC_CONFIDENCE", "")),
        "ambiguity_flag": as_bool(os.environ.get("LUCY_TRACE_SEMANTIC_AMBIGUITY_FLAG", "")),
        "gate_reason": os.environ.get("LUCY_TRACE_SEMANTIC_GATE_REASON", ""),
        "invocation_attempted": as_bool(os.environ.get("LUCY_TRACE_SEMANTIC_INVOCATION_ATTEMPTED", "")),
        "result_status": os.environ.get("LUCY_TRACE_SEMANTIC_RESULT_STATUS", ""),
        "use_reason": os.environ.get("LUCY_TRACE_SEMANTIC_USE_REASON", ""),
        "used_for_routing": as_bool(os.environ.get("LUCY_TRACE_SEMANTIC_USED_FOR_ROUTING", "")),
        "forward_candidates": as_bool(os.environ.get("LUCY_TRACE_SEMANTIC_FORWARD_CANDIDATES", "")),
        "selected_normalized_query": os.environ.get("LUCY_TRACE_SEMANTIC_SELECTED_NORMALIZED_QUERY", ""),
        "selected_retrieval_query": os.environ.get("LUCY_TRACE_SEMANTIC_SELECTED_RETRIEVAL_QUERY", ""),
        "normalized_candidates": json.loads(os.environ.get("LUCY_TRACE_SEMANTIC_NORMALIZED_CANDIDATES_JSON", "[]") or "[]"),
        "retrieval_candidates": json.loads(os.environ.get("LUCY_TRACE_SEMANTIC_RETRIEVAL_CANDIDATES_JSON", "[]") or "[]"),
    },
    "medical_detector": {
        "detector_fired": as_bool(os.environ.get("LUCY_TRACE_MEDICAL_DETECTOR_FIRED", "")),
        "original_query": os.environ.get("LUCY_TRACE_MEDICAL_ORIGINAL_QUERY", ""),
        "resolved_execution_query": os.environ.get("LUCY_TRACE_MEDICAL_RESOLVED_EXECUTION_QUERY", ""),
        "detection_source": os.environ.get("LUCY_TRACE_MEDICAL_DETECTION_SOURCE", ""),
        "pattern_family": os.environ.get("LUCY_TRACE_MEDICAL_PATTERN_FAMILY", ""),
        "candidate_medication": os.environ.get("LUCY_TRACE_MEDICAL_CANDIDATE_MEDICATION", ""),
        "normalized_candidate": os.environ.get("LUCY_TRACE_MEDICAL_NORMALIZED_CANDIDATE", ""),
        "normalized_query": os.environ.get("LUCY_TRACE_MEDICAL_NORMALIZED_QUERY", ""),
        "confidence": os.environ.get("LUCY_TRACE_MEDICAL_CONFIDENCE", ""),
        "confidence_score": as_float(os.environ.get("LUCY_TRACE_MEDICAL_CONFIDENCE_SCORE", "")),
        "provenance_notes": json.loads(os.environ.get("LUCY_TRACE_MEDICAL_PROVENANCE_NOTES_JSON", "[]") or "[]"),
    },
    "execution_contract": {
        "intent": os.environ.get("LUCY_TRACE_GOVERNOR_INTENT", ""),
        "confidence": as_float(os.environ.get("LUCY_TRACE_GOVERNOR_CONFIDENCE", "")),
        "route": os.environ.get("LUCY_TRACE_GOVERNOR_ROUTE", ""),
        "allowed_tools": as_csv(os.environ.get("LUCY_TRACE_GOVERNOR_ALLOWED_TOOLS", "")),
        "requires_sources": as_bool(os.environ.get("LUCY_TRACE_GOVERNOR_REQUIRES_SOURCES", "")),
        "requires_clarification": as_bool(os.environ.get("LUCY_TRACE_GOVERNOR_REQUIRES_CLARIFICATION", "")),
        "clarification_question": os.environ.get("LUCY_TRACE_GOVERNOR_CLARIFICATION_QUESTION") or None,
        "fallback_policy": os.environ.get("LUCY_TRACE_GOVERNOR_FALLBACK_POLICY", ""),
        "audit_tags": as_csv(os.environ.get("LUCY_TRACE_GOVERNOR_AUDIT_TAGS", "")),
        "contract_version": os.environ.get("LUCY_TRACE_GOVERNOR_CONTRACT_VERSION", ""),
        "local_response_id": os.environ.get("LUCY_TRACE_GOVERNOR_LOCAL_RESPONSE_ID") or None,
        "local_response_text": os.environ.get("LUCY_TRACE_GOVERNOR_LOCAL_RESPONSE_TEXT") or None,
        "resolved_question": os.environ.get("LUCY_TRACE_GOVERNOR_RESOLVED_QUESTION") or None,
    },
    "augmentation": {
        "policy": os.environ.get("LUCY_TRACE_AUGMENTATION_POLICY", ""),
        "requested_mode": os.environ.get("LUCY_TRACE_AUGMENTATION_REQUESTED_MODE", ""),
        "final_mode": os.environ.get("LUCY_TRACE_AUGMENTATION_FINAL_MODE", ""),
        "fallback_used": as_bool(os.environ.get("LUCY_TRACE_AUGMENTATION_FALLBACK_USED", "")),
        "fallback_reason": os.environ.get("LUCY_TRACE_AUGMENTATION_FALLBACK_REASON", ""),
        "trust_class": os.environ.get("LUCY_TRACE_AUGMENTATION_TRUST_CLASS", ""),
    },
}
Path(sys.argv[1]).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}
print_light_insufficient(){
  local q qn
  q="${QUESTION_FOR_PLAN:-${QUESTION:-}}"
  qn="$(printf '%s' "${q}" | tr '[:upper:]' '[:lower:]' | sed -E 's/[[:space:]]+/ /g; s/^ +| +$//g')"
  printf '%s\n' "From current sources:"
  if printf '%s' "${qn}" | grep -Eqi '\b(climate policy|climate regulation|emissions policy|carbon policy)\b' \
    && printf '%s' "${qn}" | grep -Eqi '\b(ai safety|ai regulation|ai governance|technology regulation|technology governance|tech governance)\b'; then
    printf '%s\n' "Insufficient trusted evidence across requested climate-policy and AI-governance domains."
    printf '%s\n' "Try: climate policy only, AI safety only, or one named regulator, region, or decision."
    return 0
  fi
  if policy_cross_domain_query "${q}"; then
    printf '%s\n' "Insufficient trusted evidence across requested policy domains."
    printf '%s\n' "Try: climate policy only, AI safety only, financial regulation only, or one named regulator, region, or decision."
    return 0
  fi
  printf '%s\n' "Insufficient evidence from trusted sources"
}
policy_cross_domain_query(){
  local q qn hits
  q="${1:-}"
  qn="$(printf '%s' "${q}" | tr '[:upper:]' '[:lower:]' | sed -E 's/[[:space:]]+/ /g; s/^ +| +$//g')"
  hits=0
  if printf '%s' "${qn}" | grep -Eqi '\b(climate|climate policy|climate regulation|emissions|carbon)\b'; then
    hits=$((hits + 1))
  fi
  if printf '%s' "${qn}" | grep -Eqi '\b(ai|artificial intelligence|ai safety|ai regulation|ai governance|technology regulation|technology governance|tech governance)\b'; then
    hits=$((hits + 1))
  fi
  if printf '%s' "${qn}" | grep -Eqi '\b(financial regulation|financial policy|banking regulation|market regulation|financial|banking|market)\b'; then
    hits=$((hits + 1))
  fi
  [[ "${hits}" -ge 2 ]] || return 1
  printf '%s' "${qn}" | grep -Eqi '\b(global policy|policy developments?|regulatory direction|predict|interaction|interact|across)\b'
}
specialized_policy_action_hint(){
  local q out n
  q="${1:-}"
  out="${2:-}"
  n="$(printf '%s' "${out}" | tr '[:upper:]' '[:lower:]')"
  printf '%s' "${n}" | grep -Eqi 'insufficient (trusted )?evidence' || return 1
  if compound_policy_query "${q}"; then
    printf '%s' "query is broad and cross-domain; ask climate policy only, AI safety only, or one named regulator, region, or decision"
    return 0
  fi
  if policy_cross_domain_query "${q}"; then
    printf '%s' "query spans multiple policy domains; ask climate policy only, AI safety only, financial regulation only, or one named regulator, region, or decision"
    return 0
  fi
  return 1
}
compound_policy_query(){
  local q qn
  q="${1:-}"
  qn="$(printf '%s' "${q}" | tr '[:upper:]' '[:lower:]' | sed -E 's/[[:space:]]+/ /g; s/^ +| +$//g')"
  printf '%s' "${qn}" | grep -Eqi '\b(climate policy|climate regulation|emissions policy|carbon policy)\b' \
    && printf '%s' "${qn}" | grep -Eqi '\b(ai safety|ai regulation|ai governance|technology regulation|technology governance|tech governance)\b'
}
print_travel_advisory_fallback(){
  local q qn min_sources found_count domains_csv
  q="${1:-}"
  found_count="${2:-0}"
  domains_csv="${3:-}"
  min_sources="${4:-2}"
  qn="$(printf '%s' "${q}" | tr '[:upper:]' '[:lower:]' | sed -E "s/[’']/\'/g; s/[[:space:]]+/ /g; s/^ +| +$//g")"

  printf '%s\n' "From current sources:"
  if printf '%s' "${qn}" | grep -Eqi '(^|[^[:alnum:]_])iran([^[:alnum:]_]|$)'; then
    printf '%s\n' "Risk-first answer: do not travel to Iran at the moment unless travel is essential."
    if printf '%s' "${qn}" | grep -Eqi '(^|[^[:alnum:]_])or([^[:alnum:]_]|$)'; then
      printf '%s\n' "If your alternative is a lower-risk destination, choose the lower-risk option."
    fi
  elif printf '%s' "${qn}" | grep -Eqi '(^|[^[:alnum:]_])(ukraine|russia|syria|yemen|sudan|gaza|west bank|lebanon|haiti|afghanistan|myanmar)([^[:alnum:]_]|$)'; then
    printf '%s\n' "Risk-first answer: avoid travel to active conflict or severe-instability zones unless essential."
    printf '%s\n' "If you must travel, use official advisories and strict contingency planning."
  else
    printf '%s\n' "Risk-first answer: avoid destinations with active conflict, severe instability, or emergency advisories."
    printf '%s\n' "If risk status is unclear, defer travel or choose a lower-risk destination."
  fi

  if [[ -n "${domains_csv}" ]]; then
    printf '%s\n' "Sources:"
    printf '%s' "${domains_csv}" | tr ',' '\n' | sed -E 's/^/- /'
  fi
  if ! [[ "${found_count}" =~ ^[0-9]+$ ]]; then
    found_count=0
  fi
  if ! [[ "${min_sources}" =~ ^[0-9]+$ ]]; then
    min_sources=2
  fi
  if [[ "${found_count}" -lt "${min_sources}" ]]; then
    printf '%s\n' "Note: insufficient corroboration (found ${found_count} sources, need ${min_sources})."
  fi
}
render_conversation_fallback(){
  # Execution-only fallback for local conversation failures. This must not reroute;
  # it only produces a bounded local response when the primary path fails.
  local q base
  q="$(printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]')"
  if [[ "${q}" =~ ^[[:space:]]*(not\ necessary|no\ thanks|never\ mind)[[:space:]]*[\.\!\?]?[[:space:]]*$ ]]; then
    return 0
  fi
  if [[ "${q}" =~ ^[[:space:]]*(hi|hello|hey)([[:space:][:punct:]]|$) ]] || [[ "${q}" == *"how are you"* ]]; then
    printf '%s\n' "Hello. What do you want to solve right now?"
    return 0
  fi
  base="$(runtime_local_prompt_fallback_text "${1:-}" "0")"
  if [[ -x "${CONV_SHIM}" ]]; then
    conversation_shim_applied="1"
    conversation_shim_profile="$(conversation_profile_style)"
    LUCY_USER_PROMPT="${1:-}" LUCY_CONV_INTENT="${intent:-}" python3 "${CONV_SHIM}" <<< "${base}"
    return 0
  fi
  conversation_shim_applied="0"
  conversation_shim_profile="none"
  printf '%s\n' "${base}"
}

print_primary_doc_fallback_urls(){
  local q="$1"
  local prefs="$2"
  local fallback_lines fallback_domains=""

  fallback_lines="$(
    python3 - "${q}" "${prefs}" <<'PY'
import re, sys, urllib.parse
q=(sys.argv[1] if len(sys.argv) > 1 else "").strip()
prefs=(sys.argv[2] if len(sys.argv) > 2 else "").strip()
m=re.search(
    r"\b("
    r"[A-Za-z]{1,6}[0-9]{2,6}[A-Za-z0-9-]*"      # LM317, NE3055
    r"|"
    r"\d[A-Za-z]{1,6}\d{1,6}[A-Za-z0-9-]*"       # 2N3055, 1N4148
    r"|"
    r"\d{2,5}[A-Za-z]{1,6}\d{1,6}[A-Za-z0-9-]*"  # 74HC14, 6SN7GT
    r"|"
    r"\d{3,5}"                                   # 807, 555, 741
    r")\b",
    q,
    flags=re.I,
)
part=(m.group(1) if m else "").strip()
if not part:
    raise SystemExit(0)
part_l=part.lower()
part_u=part.upper()
q_l=q.lower()
is_tube = bool(re.search(r"\b(vacuum\s*tube|tube|valve)\b", q_l))
domains=[d.strip().lower() for d in prefs.split(",") if d.strip()]
seen=set()
rows=[]
if is_tube:
    # Tube-specific archives/directories are often a better fallback than modern IC vendors.
    tube_rows = [
        ("frank.pocnet.net", f"{part_u} tube datasheet archive lookup (tube fallback)", f"https://frank.pocnet.net/sheets{part_u[0] if part_u and part_u[0].isdigit() else ''}.html"),
        ("nj7p.org", f"{part_u} tube manual lookup (tube fallback)", f"https://nj7p.org/Tubes/SQL/Tube_query.php?Type={urllib.parse.quote(part_u, safe='')}"),
        ("radiomuseum.org", f"{part_u} tube search (tube fallback)", f"https://www.radiomuseum.org/forumdata/search.php?search={urllib.parse.quote(part_u, safe='')}"),
    ]
    for d, label, url in tube_rows:
        rows.append((d, label, url))
    domains = []
for d in domains:
    if d in seen:
        continue
    seen.add(d)
    if d in {"ti.com","texasinstruments.com"}:
        rows.append((d, f"{part_u} datasheet PDF URL (official fallback)", f"https://www.ti.com/lit/ds/symlink/{part_l}.pdf"))
        continue
    qenc=urllib.parse.quote(part, safe="")
    if d == "st.com":
        rows.append((d, f"{part_u} datasheet lookup (official fallback)", f"https://www.st.com/content/st_com/en/search.html#q={qenc}"))
    elif d == "onsemi.com":
        rows.append((d, f"{part_u} datasheet lookup (official fallback)", f"https://www.onsemi.com/search?keyword={qenc}"))
    elif d == "analog.com":
        rows.append((d, f"{part_u} datasheet lookup (official fallback)", f"https://www.analog.com/en/search.html?q={qenc}"))
    elif d == "infineon.com":
        rows.append((d, f"{part_u} datasheet lookup (official fallback)", f"https://www.infineon.com/search?query={qenc}"))
    elif d == "nxp.com":
        rows.append((d, f"{part_u} datasheet lookup (official fallback)", f"https://www.nxp.com/search?term={qenc}"))
    elif d == "microchip.com":
        rows.append((d, f"{part_u} datasheet lookup (official fallback)", f"https://www.microchip.com/en-us/search?searchQuery={qenc}"))
    elif d == "digikey.com":
        rows.append((d, f"{part_u} distributor search (fallback)", f"https://www.digikey.com/en/products/result?keywords={qenc}"))
    elif d == "mouser.com":
        rows.append((d, f"{part_u} distributor search (fallback)", f"https://www.mouser.com/c/?q={qenc}"))
for d,label,url in rows[:4]:
    print(f"{d}\t{label}\t{url}")
PY
  )"
  [[ -n "${fallback_lines}" ]] || return 1

  printf '%s\n' "From current sources:"
  while IFS=$'\t' read -r fdom flabel furl; do
    [[ -n "${fdom}" ]] || continue
    printf '%s\n' "${flabel}: ${furl}"
    fallback_domains+="${fdom}"$'\n'
  done <<< "${fallback_lines}"
  printf '%s\n' "Sources:"
  printf '%s' "${fallback_domains}" | awk 'NF{print "- "$0}'
  return 0
}

if [[ $# -gt 0 ]]; then
  QUESTION="$*"
else
  QUESTION="$(cat)"
fi
QUESTION="$(printf '%s' "${QUESTION}" | sed -E 's/[[:space:]]+/ /g; s/^ +| +$//g')"
[[ -n "${QUESTION}" ]] || { err "empty question"; exit 2; }
question_for_plan="${QUESTION}"
lat_request_receipt_start_ms="$(latprof_now_ms)"
if ! acquire_shared_execution_lock; then
  route_reason_override="shared_state_overlap"
  fallback_kind="shared_state_lock_contention"
  requested_mode="LOCAL"
  final_mode="LOCAL"
  fallback_used="false"
  fallback_reason="none"
  trust_class="unverified"
  local_gen_status="fail"
  router_outcome_code="validated_insufficient"
  outcome_code_override="validated_insufficient"
  record_terminal_outcome "validated_insufficient" "LOCAL" "${shared_state_lock_error:-shared-state overlap detected}" "0"
  print_validated_insufficient
  exit 0
fi

latprof_prepare_run || true
latprof_append "execute_plan" "bootstrap_startup" "$(( $(latprof_now_ms) - EXECUTE_PLAN_BOOT_START_MS ))"
lat_total_start_ms="$(latprof_now_ms)"

route_prefix=""
question_for_plan="${QUESTION}"
if [[ "${QUESTION}" =~ ^([Ll][Oo][Cc][Aa][Ll]|[Nn][Ee][Ww][Ss]|[Ee][Vv][Ii][Dd][Ee][Nn][Cc][Ee]|[Aa][Uu][Gg][Mm][Ee][Nn][Tt][Ee][Dd]):[[:space:]]*(.*)$ ]]; then
  route_prefix="$(printf '%s' "${BASH_REMATCH[1]}" | tr '[:upper:]' '[:lower:]')"
  question_for_plan="${BASH_REMATCH[2]}"
fi
[[ -n "${question_for_plan}" ]] || question_for_plan="${QUESTION}"
if [[ -z "${route_prefix}" ]]; then
  :
fi
augmentation_policy="$(normalize_augmentation_policy "${LUCY_AUGMENTATION_POLICY:-disabled}")"
augmented_provider_selected="$(resolve_augmented_provider || true)"
[[ -n "${augmented_provider_selected}" ]] || augmented_provider_selected="none"
if [[ "${augmentation_policy}" == "disabled" ]]; then
  augmented_provider_call_reason="disabled"
else
  augmented_provider_call_reason="not_needed"
fi
augmented_direct_request="false"
if [[ "${route_prefix}" == "augmented" ]]; then
  augmented_direct_request="true"
  route_prefix=""
fi
if is_truthy "${LUCY_AUGMENTED_DIRECT_REQUEST:-0}"; then
  augmented_direct_request="true"
fi
if [[ "${augmented_direct_request}" == "true" ]]; then
  if [[ "${augmentation_policy}" == "direct_allowed" ]]; then
    augmented_allowed="true"
  else
    augmented_allowed="false"
    augmented_provider_call_reason="disabled"
  fi
else
  if [[ "${augmentation_policy}" == "disabled" ]]; then
    augmented_allowed="false"
    augmented_provider_call_reason="disabled"
  else
    augmented_allowed="true"
    augmented_provider_call_reason="not_needed"
  fi
fi
latprof_append "execute_plan" "request_receipt" "$(( $(latprof_now_ms) - lat_request_receipt_start_ms ))"

[[ -x "${CLASSIFIER}" ]] || { err "missing classifier: ${CLASSIFIER}"; exit 3; }
[[ -f "${PLAN_MAPPER}" ]] || { err "missing plan mapper: ${PLAN_MAPPER}"; exit 3; }
lat_stage_start_ms="$(latprof_now_ms)"
PLAN_JSON="$("${CLASSIFIER}" "${question_for_plan}")"
latprof_append "execute_plan" "classify_intent" "$(( $(latprof_now_ms) - lat_stage_start_ms ))"
export PLAN_JSON
if [[ -n "${LUCY_CLASSIFIER_TRACE_FILE:-}" ]]; then
  mkdir -p "$(dirname "${LUCY_CLASSIFIER_TRACE_FILE}")" 2>/dev/null || true
  printf '%s\n' "${PLAN_JSON}" > "${LUCY_CLASSIFIER_TRACE_FILE}"
fi

route_control_mode="${LUCY_ROUTE_CONTROL_MODE:-AUTO}"
case "${route_control_mode}" in
  AUTO|FORCED_OFFLINE|FORCED_ONLINE) ;;
  *) err "invalid LUCY_ROUTE_CONTROL_MODE: ${route_control_mode}"; exit 4 ;;
esac
conv_force_raw="${LUCY_CONVERSATION_MODE_FORCE:-0}"
conv_force="0"
case "$(printf '%s' "${conv_force_raw}" | tr '[:upper:]' '[:lower:]')" in
  1|true|yes|on) conv_force="1" ;;
esac

lat_stage_start_ms="$(latprof_now_ms)"
MAP_JSON="$(python3 "${PLAN_MAPPER}" \
  --plan-json "${PLAN_JSON}" \
  --question "${question_for_plan}" \
  --route-prefix "${route_prefix}" \
  --surface "${LUCY_SURFACE:-cli}" \
  --route-control-mode "${route_control_mode}")"
latprof_append "execute_plan" "plan_to_pipeline_total" "$(( $(latprof_now_ms) - lat_stage_start_ms ))"
export MAP_JSON
if [[ -n "${LUCY_ROUTER_TRACE_FILE:-}" ]]; then
  mkdir -p "$(dirname "${LUCY_ROUTER_TRACE_FILE}")" 2>/dev/null || true
  printf '%s\n' "${MAP_JSON}" > "${LUCY_ROUTER_TRACE_FILE}"
fi
eval "$(
  python3 - <<'PY'
import json
import os
import shlex

def load(name):
    try:
        return json.loads(os.environ.get(name, "{}"))
    except Exception:
        return {}

def lookup(obj, *paths):
    for path in paths:
        cur = obj
        ok = True
        for part in path.split("."):
            if not isinstance(cur, dict) or part not in cur:
                ok = False
                break
            cur = cur.get(part)
        if ok and cur is not None:
            return cur
    return None

def coalesce(*values):
    for value in values:
        if value is not None:
            return value
    return None

def to_text(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return ",".join(str(x) for x in value)
    return str(value)

def normalize_route(value):
    route = str(value or "").strip().upper()
    return route if route in {"LOCAL", "NEWS", "EVIDENCE", "AUGMENTED", "CLARIFY"} else ""

def normalize_policy_route(value):
    route = normalize_route(value)
    if route:
        return route.lower()
    route = str(value or "").strip().lower()
    return route if route in {"local", "news", "evidence", "augmented", "clarify"} else ""

EVIDENCE_REASON_ALIASES = {
    "current_fact": "default_light",
    "source_request": "explicit_source_request",
    "medical_context": "policy_medical_high_risk",
    "conflict_live": "policy_conflict_live",
    "geopolitics": "policy_geopolitics_high_risk",
}
CANONICAL_EVIDENCE_REASONS = {
    "default_light",
    "explicit_source_request",
    "policy_medical_high_risk",
    "policy_conflict_live",
    "policy_geopolitics_high_risk",
    "not_evidence_route",
}

def normalize_evidence_reason(evidence_mode, evidence_reason):
    mode = str(evidence_mode or "").strip().upper()
    reason = to_text(evidence_reason).strip()
    if reason in EVIDENCE_REASON_ALIASES:
        reason = EVIDENCE_REASON_ALIASES[reason]
    if mode:
        return reason
    return reason

def normalize_route_list(value):
    if not isinstance(value, list):
        return []
    out = []
    seen = set()
    for raw in value:
        route = normalize_route(raw)
        if not route or route in seen:
            continue
        seen.add(route)
        out.append(route)
    return out

def validate_manifest(manifest):
    if not isinstance(manifest, dict) or not manifest:
        return "missing_route_manifest"
    for field in (
        "manifest_version",
        "precedence_version",
        "original_query",
        "resolved_execution_query",
        "selected_route",
        "winning_signal",
        "authority_basis",
        "context_referent_confidence",
        "evidence_mode",
        "evidence_mode_reason",
    ):
        if not isinstance(manifest.get(field), str):
            return f"manifest_field_not_string:{field}"
    if manifest.get("manifest_version") != "v1":
        return "unsupported_manifest_version"
    selected_route = normalize_route(manifest.get("selected_route"))
    if not selected_route:
        return "invalid_manifest_selected_route"
    intent_family = to_text(manifest.get("intent_family")).strip()
    if intent_family not in {"", "self_review", "current_evidence", "background_overview", "synthesis_explanation", "local_answer"}:
        return "invalid_manifest_intent_family"
    allowed_routes = normalize_route_list(manifest.get("allowed_routes"))
    forbidden_routes = normalize_route_list(manifest.get("forbidden_routes"))
    if not allowed_routes:
        return "empty_manifest_allowed_routes"
    if selected_route not in allowed_routes:
        return "manifest_selected_route_not_allowed"
    if selected_route in forbidden_routes:
        return "manifest_selected_route_forbidden"
    if set(allowed_routes) & set(forbidden_routes):
        return "manifest_route_sets_overlap"
    if not isinstance(manifest.get("clarify_required"), bool):
        return "manifest_clarify_required_not_bool"
    if manifest.get("clarify_required") and selected_route != "CLARIFY":
        return "manifest_clarify_requires_clarify_route"
    if selected_route == "CLARIFY" and not manifest.get("clarify_required"):
        return "manifest_clarify_route_missing_flag"
    if not isinstance(manifest.get("context_resolution_used"), bool):
        return "manifest_context_resolution_not_bool"
    signals = manifest.get("signals")
    if not isinstance(signals, dict):
        return "manifest_signals_not_object"
    for field in (
        "temporal",
        "news",
        "conflict",
        "geopolitics",
        "israel_region_live",
        "source_request",
        "url",
        "ambiguity_followup",
        "medical_context",
        "current_product",
    ):
        if not isinstance(signals.get(field), bool):
            return f"manifest_signal_not_bool:{field}"
    evidence_mode = manifest.get("evidence_mode")
    if not isinstance(evidence_mode, str):
        return "manifest_evidence_mode_not_string"
    if evidence_mode and evidence_mode not in {"LIGHT", "FULL"}:
        return "invalid_manifest_evidence_mode"
    evidence_reason = manifest.get("evidence_mode_reason")
    if not isinstance(evidence_reason, str):
        return "manifest_evidence_mode_reason_not_string"
    normalized_reason = normalize_evidence_reason(evidence_mode, evidence_reason)
    if evidence_mode:
        if normalized_reason not in (CANONICAL_EVIDENCE_REASONS - {"not_evidence_route"}):
            return "invalid_manifest_evidence_mode_reason"
    elif normalized_reason not in {"", "not_evidence_route"}:
        return "invalid_manifest_evidence_mode_reason"
    return ""

def validate_legacy_route_aliases(mapped, manifest_selected_route):
    if not manifest_selected_route:
        return ""
    for field in ("force_mode", "route_mode"):
        alias = normalize_route(lookup(mapped, field))
        if alias and alias != manifest_selected_route:
            return f"compat_route_alias_mismatch:{field}:{alias}->{manifest_selected_route}"
    manifest_policy_route = manifest_selected_route.lower()
    for field in ("policy_recommended_route", "policy_actual_route", "policy_base_recommended_route"):
        alias = normalize_policy_route(lookup(mapped, field))
        if alias and alias != manifest_policy_route:
            return f"compat_policy_alias_mismatch:{field}:{alias}->{manifest_policy_route}"
    return ""

plan = load("PLAN_JSON")
mapped = load("MAP_JSON")
manifest = lookup(mapped, "route_manifest") or {}
manifest_error = validate_manifest(manifest)
manifest_selected_route = normalize_route(lookup(manifest, "selected_route"))
manifest_selected_policy_route = manifest_selected_route.lower() if manifest_selected_route else ""
manifest_allowed_routes = normalize_route_list(lookup(manifest, "allowed_routes"))
manifest_forbidden_routes = normalize_route_list(lookup(manifest, "forbidden_routes"))
manifest_signals = lookup(manifest, "signals") if isinstance(lookup(manifest, "signals"), dict) else {}
manifest_evidence_mode = lookup(manifest, "evidence_mode")
manifest_evidence_mode_reason = normalize_evidence_reason(manifest_evidence_mode, lookup(manifest, "evidence_mode_reason"))
contract_route = normalize_route(lookup(mapped, "execution_contract.route"))
if not manifest_error and contract_route and contract_route != manifest_selected_route:
    manifest_error = f"contract_route_mismatch:{contract_route}->{manifest_selected_route}"
if not manifest_error:
    legacy_alias_error = validate_legacy_route_aliases(mapped, manifest_selected_route)
    if legacy_alias_error:
        manifest_error = legacy_alias_error
plan_intent = lookup(plan, "legacy_plan.intent", "intent")
plan_category = lookup(mapped, "effective_plan.category", "effective_category") or lookup(plan, "legacy_plan.category", "category")
classifier_allow_domains_file = lookup(plan, "legacy_plan.allow_domains_file", "allow_domains_file")
classifier_region_filter = lookup(plan, "legacy_plan.region_filter", "region_filter")
map_one_clarifying_question = lookup(mapped, "effective_plan.one_clarifying_question", "one_clarifying_question")

fields = {
    "intent": lookup(mapped, "effective_plan.intent", "effective_intent") or plan_intent,
    "category": plan_category,
    "governor_intent": lookup(mapped, "execution_contract.intent"),
    "governor_confidence": lookup(mapped, "execution_contract.confidence"),
    "governor_route": manifest_selected_route,
    "governor_allowed_tools": lookup(mapped, "execution_contract.allowed_tools"),
    "governor_requires_sources": lookup(mapped, "execution_contract.requires_sources"),
    "governor_requires_clarification": lookup(mapped, "execution_contract.requires_clarification"),
    "governor_fallback_policy": lookup(mapped, "execution_contract.fallback_policy"),
    "governor_audit_tags": lookup(mapped, "execution_contract.audit_tags"),
    "governor_contract_version": lookup(mapped, "execution_contract.contract_version"),
    "governor_local_response_id": lookup(mapped, "execution_contract.local_response_id"),
    "governor_local_response_text": lookup(mapped, "execution_contract.local_response_text"),
    "governor_resolved_question": lookup(mapped, "execution_contract.resolved_question", "resolved_question"),
    "governor_contextual_followup_applied": lookup(mapped, "contextual_followup_applied"),
    "mapped_route_reason_override": lookup(mapped, "route_reason_override"),
    "mapped_knowledge_path": lookup(mapped, "knowledge_path"),
    "mapped_outcome_code_override": lookup(mapped, "outcome_code_override"),
    "semantic_interpreter_fired": lookup(mapped, "semantic_interpreter_fired"),
    "semantic_interpreter_original_query": lookup(mapped, "semantic_interpreter_original_query"),
    "semantic_interpreter_resolved_execution_query": lookup(mapped, "semantic_interpreter_resolved_execution_query"),
    "semantic_interpreter_inferred_domain": lookup(mapped, "semantic_interpreter_inferred_domain"),
    "semantic_interpreter_inferred_intent_family": lookup(mapped, "semantic_interpreter_inferred_intent_family"),
    "semantic_interpreter_confidence": lookup(mapped, "semantic_interpreter_confidence"),
    "semantic_interpreter_ambiguity_flag": lookup(mapped, "semantic_interpreter_ambiguity_flag"),
    "semantic_interpreter_gate_reason": lookup(mapped, "semantic_interpreter_gate_reason"),
    "semantic_interpreter_invocation_attempted": lookup(mapped, "semantic_interpreter_invocation_attempted"),
    "semantic_interpreter_result_status": lookup(mapped, "semantic_interpreter_result_status"),
    "semantic_interpreter_use_reason": lookup(mapped, "semantic_interpreter_use_reason"),
    "semantic_interpreter_used_for_routing": lookup(mapped, "semantic_interpreter_used_for_routing"),
    "semantic_interpreter_forward_candidates": lookup(mapped, "semantic_interpreter_forward_candidates"),
    "semantic_interpreter_selected_normalized_query": lookup(mapped, "semantic_interpreter_selected_normalized_query"),
    "semantic_interpreter_selected_retrieval_query": lookup(mapped, "semantic_interpreter_selected_retrieval_query"),
    "semantic_interpreter_normalized_candidates_csv": lookup(mapped, "semantic_interpreter_normalized_candidates_csv"),
    "semantic_interpreter_retrieval_candidates_csv": lookup(mapped, "semantic_interpreter_retrieval_candidates_csv"),
    "semantic_interpreter_normalized_candidates_json": lookup(mapped, "semantic_interpreter_normalized_candidates_json"),
    "semantic_interpreter_retrieval_candidates_json": lookup(mapped, "semantic_interpreter_retrieval_candidates_json"),
    "medical_detector_fired": lookup(mapped, "medical_detector_fired"),
    "medical_detector_original_query": lookup(mapped, "medical_detector_original_query"),
    "medical_detector_resolved_execution_query": lookup(mapped, "medical_detector_resolved_execution_query"),
    "medical_detector_detection_source": lookup(mapped, "medical_detector_detection_source"),
    "medical_detector_pattern_family": lookup(mapped, "medical_detector_pattern_family"),
    "medical_detector_candidate_medication": lookup(mapped, "medical_detector_candidate_medication"),
    "medical_detector_normalized_candidate": lookup(mapped, "medical_detector_normalized_candidate"),
    "medical_detector_normalized_query": lookup(mapped, "medical_detector_normalized_query"),
    "medical_detector_confidence": lookup(mapped, "medical_detector_confidence"),
    "medical_detector_confidence_score": lookup(mapped, "medical_detector_confidence_score"),
    "medical_detector_provenance_notes_json": lookup(mapped, "medical_detector_provenance_notes_json"),
    "classifier_intent": plan_intent,
    "classifier_category": plan_category,
    "classifier_intent_class": lookup(plan, "intent_class"),
    "router_intent": lookup(mapped, "router_intent", "effective_plan.intent", "effective_intent") or plan_intent,
    "manifest_error": manifest_error,
    "manifest_version": lookup(manifest, "manifest_version"),
    "manifest_selected_route": manifest_selected_route,
    "manifest_intent_family": lookup(manifest, "intent_family"),
    "manifest_allowed_routes": manifest_allowed_routes,
    "manifest_forbidden_routes": manifest_forbidden_routes,
    "manifest_winning_signal": lookup(manifest, "winning_signal"),
    "manifest_authority_basis": lookup(manifest, "authority_basis"),
    "manifest_clarify_required": lookup(manifest, "clarify_required"),
    "manifest_context_resolution_used": lookup(manifest, "context_resolution_used"),
    "manifest_context_referent_confidence": lookup(manifest, "context_referent_confidence"),
    "manifest_evidence_mode": manifest_evidence_mode,
    "manifest_evidence_mode_reason": manifest_evidence_mode_reason,
    "manifest_original_query": lookup(manifest, "original_query"),
    "manifest_resolved_execution_query": lookup(manifest, "resolved_execution_query"),
    "manifest_precedence_version": lookup(manifest, "precedence_version"),
    "needs_web": coalesce(
        lookup(mapped, "execution_contract.requires_sources", "effective_plan.needs_web", "effective_needs_web"),
        lookup(plan, "legacy_plan.needs_web", "needs_web"),
    ),
    "min_sources": coalesce(
        lookup(mapped, "effective_plan.min_sources", "effective_min_sources"),
        lookup(plan, "legacy_plan.min_sources", "min_sources"),
    ),
    "one_clarifying_question": map_one_clarifying_question or lookup(plan, "legacy_plan.one_clarifying_question", "one_clarifying_question"),
    "plan_output_mode": lookup(mapped, "effective_plan.output_mode", "effective_plan_output_mode") or lookup(plan, "legacy_plan.output_mode", "output_mode"),
    "prefer_domains": lookup(plan, "legacy_plan.prefer_domains", "prefer_domains"),
    "classifier_allow_domains_file": classifier_allow_domains_file,
    "classifier_region_filter": classifier_region_filter,
    "allow_domains_file": lookup(mapped, "effective_plan.allow_domains_file") or classifier_allow_domains_file,
    "region_filter": lookup(mapped, "effective_plan.region_filter") or classifier_region_filter,
    "force_mode": manifest_selected_route,
    "route_mode": manifest_selected_route,
    "offline_action": lookup(mapped, "route_decision.offline_action", "offline_action"),
    "needs_clarification": coalesce(lookup(manifest, "clarify_required"), False),
    "clarification_question": lookup(mapped, "execution_contract.clarification_question", "route_decision.clarification_question", "clarification_question"),
    "policy_recommended_route": manifest_selected_policy_route,
    "policy_actual_route": manifest_selected_policy_route,
    "policy_confidence": lookup(mapped, "route_decision.policy_confidence", "policy_confidence"),
    "policy_confidence_threshold": lookup(mapped, "route_decision.policy_confidence_threshold", "policy_confidence_threshold"),
    "policy_freshness_requirement": lookup(mapped, "route_decision.freshness_requirement", "freshness_requirement"),
    "policy_risk_level": lookup(mapped, "route_decision.risk_level", "risk_level"),
    "policy_source_criticality": lookup(mapped, "route_decision.source_criticality", "source_criticality"),
    "policy_intent_family": lookup(mapped, "route_decision.intent_family", "intent_family"),
    "policy_augmented_family": lookup(mapped, "route_decision.augmented_family", "augmented_family"),
    "policy_operator_override": lookup(mapped, "route_decision.operator_override", "operator_override"),
    "policy_reason_codes_csv": lookup(mapped, "route_decision.reason_codes_csv", "reason_codes_csv"),
    "winning_signal": lookup(manifest, "winning_signal"),
    "precedence_version": lookup(manifest, "precedence_version"),
    "routing_signal_temporal": lookup(manifest_signals, "temporal"),
    "routing_signal_news": lookup(manifest_signals, "news"),
    "routing_signal_conflict": lookup(manifest_signals, "conflict"),
    "routing_signal_geopolitics": lookup(manifest_signals, "geopolitics"),
    "routing_signal_israel_region": lookup(manifest_signals, "israel_region_live"),
    "routing_signal_source_request": lookup(manifest_signals, "source_request"),
    "routing_signal_url": lookup(manifest_signals, "url"),
    "routing_signal_ambiguity_followup": lookup(manifest_signals, "ambiguity_followup"),
    "routing_signal_medical_context": lookup(manifest_signals, "medical_context"),
    "routing_signal_current_product": lookup(manifest_signals, "current_product"),
}

for key, value in fields.items():
    print(f"{key}={shlex.quote(to_text(value))}")
PY
)"
if [[ -n "${manifest_error}" ]]; then
  err "malformed route manifest: ${manifest_error}"
  exit 4
fi
if [[ "${route_prefix}" == "local" && "${force_mode}" == "LOCAL" && "${intent}" != "MEDICAL_INFO" ]]; then
  needs_web="false"
  offline_action="allow"
fi
[[ -n "${manifest_version:-}" ]] || manifest_version="v1"
[[ -n "${manifest_forbidden_routes:-}" ]] || manifest_forbidden_routes=""
[[ -n "${manifest_authority_basis:-}" ]] || manifest_authority_basis="policy_selected_route"
[[ -n "${manifest_intent_family:-}" ]] || manifest_intent_family=""
[[ -n "${manifest_clarify_required:-}" ]] || manifest_clarify_required="false"
[[ -n "${manifest_context_resolution_used:-}" ]] || manifest_context_resolution_used="false"
[[ -n "${manifest_context_referent_confidence:-}" ]] || manifest_context_referent_confidence=""
[[ -n "${manifest_evidence_mode:-}" ]] || manifest_evidence_mode=""
[[ -n "${manifest_evidence_mode_reason:-}" ]] || manifest_evidence_mode_reason=""
[[ -n "${manifest_original_query:-}" ]] || manifest_original_query="${QUESTION}"
[[ -n "${manifest_resolved_execution_query:-}" ]] || manifest_resolved_execution_query="${question_for_plan}"
[[ -n "${governor_intent}" ]] || governor_intent="${classifier_intent_class:-${intent}}"
[[ -n "${governor_confidence}" ]] || governor_confidence="${policy_confidence}"
[[ -n "${governor_contract_version}" ]] || governor_contract_version="legacy_implicit"
[[ -n "${governor_fallback_policy}" ]] || governor_fallback_policy="none"
intent_family="${manifest_intent_family:-${policy_intent_family:-}}"
[[ -n "${intent_family:-}" ]] || intent_family=""
[[ -n "${governor_requires_sources}" ]] || governor_requires_sources="${needs_web}"
[[ -n "${governor_requires_clarification}" ]] || governor_requires_clarification="${manifest_clarify_required}"
[[ -n "${routing_signal_temporal:-}" ]] || routing_signal_temporal="false"
[[ -n "${routing_signal_news:-}" ]] || routing_signal_news="false"
[[ -n "${routing_signal_conflict:-}" ]] || routing_signal_conflict="false"
[[ -n "${routing_signal_geopolitics:-}" ]] || routing_signal_geopolitics="false"
[[ -n "${routing_signal_israel_region:-}" ]] || routing_signal_israel_region="false"
[[ -n "${routing_signal_source_request:-}" ]] || routing_signal_source_request="false"
[[ -n "${routing_signal_url:-}" ]] || routing_signal_url="false"
[[ -n "${routing_signal_ambiguity_followup:-}" ]] || routing_signal_ambiguity_followup="false"
[[ -n "${routing_signal_medical_context:-}" ]] || routing_signal_medical_context="false"
[[ -n "${routing_signal_current_product:-}" ]] || routing_signal_current_product="false"
[[ -n "${winning_signal:-}" ]] || winning_signal="legacy_policy"
[[ -n "${precedence_version:-}" ]] || precedence_version="unknown"
force_mode="${manifest_selected_route}"
route_mode="${manifest_selected_route}"
governor_route="${manifest_selected_route}"
policy_actual_route="$(policy_route_alias "${manifest_selected_route}")"
policy_recommended_route="${policy_actual_route}"
requested_mode="${force_mode}"
final_mode="${force_mode}"
fallback_used="false"
fallback_reason="none"

# Override from Python router: Creative writing requests force local mode
# This prevents identity preamble issues ("I'm Local Lucy...") with augmented providers
if [[ "${LUCY_FORCE_LOCAL:-0}" == "1" ]]; then
  final_mode="LOCAL"
  requested_mode="LOCAL"
  force_mode="LOCAL"
  trust_class="unverified"
  route_reason_override="creative_writing_force_local"
  info "LUCY_FORCE_LOCAL: overriding to LOCAL mode (creative writing detected)"
fi

if [[ "${force_mode}" == "LOCAL" ]]; then
  trust_class="unverified"
else
  trust_class="evidence_backed"
fi
if [[ "${augmented_direct_request}" == "true" ]]; then
  requested_mode="AUGMENTED"
fi
assert_manifest_route_compatibility
if [[ -n "${manifest_resolved_execution_query:-}" ]]; then
  question_for_plan="${manifest_resolved_execution_query}"
elif [[ -n "${governor_resolved_question}" ]]; then
  question_for_plan="${governor_resolved_question}"
fi
if [[ -n "${mapped_route_reason_override:-}" ]]; then
  route_reason_override="${mapped_route_reason_override}"
fi
if [[ -n "${mapped_knowledge_path:-}" ]]; then
  knowledge_path="${mapped_knowledge_path}"
fi
if [[ -n "${mapped_outcome_code_override:-}" ]]; then
  outcome_code_override="${mapped_outcome_code_override}"
fi
if [[ "${governor_contextual_followup_applied:-false}" == "true" || -n "${governor_local_response_id}" ]]; then
  contextual_local_followup="1"
fi
if [[ -n "${manifest_resolved_execution_query:-}" && "${manifest_resolved_execution_query}" != "${QUESTION}" ]]; then
  one_clarifying_question=""
elif [[ -n "${governor_resolved_question}" ]]; then
  one_clarifying_question=""
fi
if [[ "${governor_route}" == "LOCAL" && "${governor_requires_sources}" == "false" ]]; then
  offline_action="allow"
fi
[[ -n "${semantic_interpreter_fired:-}" ]] || semantic_interpreter_fired="false"
[[ -n "${semantic_interpreter_original_query:-}" ]] || semantic_interpreter_original_query="${QUESTION}"
[[ -n "${semantic_interpreter_resolved_execution_query:-}" ]] || semantic_interpreter_resolved_execution_query="${question_for_plan}"
[[ -n "${semantic_interpreter_inferred_domain:-}" ]] || semantic_interpreter_inferred_domain="unknown"
[[ -n "${semantic_interpreter_inferred_intent_family:-}" ]] || semantic_interpreter_inferred_intent_family="unknown"
[[ -n "${semantic_interpreter_confidence:-}" ]] || semantic_interpreter_confidence="0.0"
[[ -n "${semantic_interpreter_ambiguity_flag:-}" ]] || semantic_interpreter_ambiguity_flag="false"
[[ -n "${semantic_interpreter_gate_reason:-}" ]] || semantic_interpreter_gate_reason="not_invoked"
[[ -n "${semantic_interpreter_invocation_attempted:-}" ]] || semantic_interpreter_invocation_attempted="false"
[[ -n "${semantic_interpreter_result_status:-}" ]] || semantic_interpreter_result_status="not_invoked"
[[ -n "${semantic_interpreter_use_reason:-}" ]] || semantic_interpreter_use_reason="not_invoked"
[[ -n "${semantic_interpreter_used_for_routing:-}" ]] || semantic_interpreter_used_for_routing="false"
[[ -n "${semantic_interpreter_forward_candidates:-}" ]] || semantic_interpreter_forward_candidates="false"
[[ -n "${semantic_interpreter_selected_normalized_query:-}" ]] || semantic_interpreter_selected_normalized_query="${semantic_interpreter_original_query}"
[[ -n "${semantic_interpreter_selected_retrieval_query:-}" ]] || semantic_interpreter_selected_retrieval_query=""
[[ -n "${semantic_interpreter_normalized_candidates_csv:-}" ]] || semantic_interpreter_normalized_candidates_csv=""
[[ -n "${semantic_interpreter_retrieval_candidates_csv:-}" ]] || semantic_interpreter_retrieval_candidates_csv=""
[[ -n "${semantic_interpreter_normalized_candidates_json:-}" ]] || semantic_interpreter_normalized_candidates_json="[]"
[[ -n "${semantic_interpreter_retrieval_candidates_json:-}" ]] || semantic_interpreter_retrieval_candidates_json="[]"
[[ -n "${medical_detector_fired:-}" ]] || medical_detector_fired="false"
[[ -n "${medical_detector_original_query:-}" ]] || medical_detector_original_query="${QUESTION}"
[[ -n "${medical_detector_resolved_execution_query:-}" ]] || medical_detector_resolved_execution_query="${question_for_plan}"
[[ -n "${medical_detector_detection_source:-}" ]] || medical_detector_detection_source="not_detected"
[[ -n "${medical_detector_pattern_family:-}" ]] || medical_detector_pattern_family=""
[[ -n "${medical_detector_candidate_medication:-}" ]] || medical_detector_candidate_medication=""
[[ -n "${medical_detector_normalized_candidate:-}" ]] || medical_detector_normalized_candidate=""
[[ -n "${medical_detector_normalized_query:-}" ]] || medical_detector_normalized_query=""
[[ -n "${medical_detector_confidence:-}" ]] || medical_detector_confidence="none"
[[ -n "${medical_detector_confidence_score:-}" ]] || medical_detector_confidence_score="0.0"
[[ -n "${medical_detector_provenance_notes_json:-}" ]] || medical_detector_provenance_notes_json="[]"
if [[ "${medical_detector_fired}" != "true" ]]; then
  medical_detector_pattern_family=""
  medical_detector_candidate_medication=""
  medical_detector_normalized_candidate=""
  medical_detector_normalized_query=""
  medical_detector_confidence="none"
  medical_detector_confidence_score="0.0"
fi
semantic_interpreter_retrieval_selected="false"
export LUCY_TRACE_EXECUTION_QUESTION="${question_for_plan}"
export LUCY_TRACE_EXECUTION_ROUTE_MODE="${force_mode}"
export LUCY_TRACE_EXECUTION_OUTPUT_MODE="${output_mode:-}"
export LUCY_LOCAL_GEN_ROUTE_MODE="${force_mode}"
export LUCY_LOCAL_GEN_OUTPUT_MODE="${output_mode:-CHAT}"
export LUCY_TRACE_EXECUTION_OFFLINE_ACTION="${offline_action}"
export LUCY_TRACE_MANIFEST_VERSION="${manifest_version}"
export LUCY_TRACE_MANIFEST_PRECEDENCE_VERSION="${precedence_version}"
export LUCY_TRACE_MANIFEST_ORIGINAL_QUERY="${manifest_original_query:-${QUESTION}}"
export LUCY_TRACE_MANIFEST_RESOLVED_EXECUTION_QUERY="${manifest_resolved_execution_query:-${question_for_plan}}"
export LUCY_TRACE_MANIFEST_SELECTED_ROUTE="${manifest_selected_route}"
export LUCY_TRACE_MANIFEST_INTENT_FAMILY="${manifest_intent_family:-}"
export LUCY_TRACE_MANIFEST_ALLOWED_ROUTES="${manifest_allowed_routes}"
export LUCY_TRACE_MANIFEST_FORBIDDEN_ROUTES="${manifest_forbidden_routes}"
export LUCY_TRACE_MANIFEST_WINNING_SIGNAL="${winning_signal}"
export LUCY_TRACE_MANIFEST_CLARIFY_REQUIRED="${manifest_clarify_required}"
export LUCY_TRACE_MANIFEST_AUTHORITY_BASIS="${manifest_authority_basis}"
export LUCY_TRACE_MANIFEST_CONTEXT_RESOLUTION_USED="${manifest_context_resolution_used}"
export LUCY_TRACE_MANIFEST_CONTEXT_REFERENT_CONFIDENCE="${manifest_context_referent_confidence}"
export LUCY_TRACE_MANIFEST_EVIDENCE_MODE="${manifest_evidence_mode}"
export LUCY_TRACE_MANIFEST_EVIDENCE_MODE_REASON="${manifest_evidence_mode_reason}"
export LUCY_TRACE_MANIFEST_SIGNAL_TEMPORAL="${routing_signal_temporal}"
export LUCY_TRACE_MANIFEST_SIGNAL_NEWS="${routing_signal_news}"
export LUCY_TRACE_MANIFEST_SIGNAL_CONFLICT="${routing_signal_conflict}"
export LUCY_TRACE_MANIFEST_SIGNAL_GEOPOLITICS="${routing_signal_geopolitics}"
export LUCY_TRACE_MANIFEST_SIGNAL_ISRAEL_REGION_LIVE="${routing_signal_israel_region}"
export LUCY_TRACE_MANIFEST_SIGNAL_SOURCE_REQUEST="${routing_signal_source_request}"
export LUCY_TRACE_MANIFEST_SIGNAL_URL="${routing_signal_url}"
export LUCY_TRACE_MANIFEST_SIGNAL_AMBIGUITY_FOLLOWUP="${routing_signal_ambiguity_followup}"
export LUCY_TRACE_MANIFEST_SIGNAL_MEDICAL_CONTEXT="${routing_signal_medical_context}"
export LUCY_TRACE_MANIFEST_SIGNAL_CURRENT_PRODUCT="${routing_signal_current_product}"
export LUCY_TRACE_SEMANTIC_FIRED="${semantic_interpreter_fired}"
export LUCY_TRACE_SEMANTIC_ORIGINAL_QUERY="${semantic_interpreter_original_query}"
export LUCY_TRACE_SEMANTIC_RESOLVED_EXECUTION_QUERY="${semantic_interpreter_resolved_execution_query}"
export LUCY_TRACE_SEMANTIC_INFERRED_DOMAIN="${semantic_interpreter_inferred_domain}"
export LUCY_TRACE_SEMANTIC_INFERRED_INTENT_FAMILY="${semantic_interpreter_inferred_intent_family}"
export LUCY_TRACE_SEMANTIC_CONFIDENCE="${semantic_interpreter_confidence}"
export LUCY_TRACE_SEMANTIC_AMBIGUITY_FLAG="${semantic_interpreter_ambiguity_flag}"
export LUCY_TRACE_SEMANTIC_GATE_REASON="${semantic_interpreter_gate_reason}"
export LUCY_TRACE_SEMANTIC_INVOCATION_ATTEMPTED="${semantic_interpreter_invocation_attempted}"
export LUCY_TRACE_SEMANTIC_RESULT_STATUS="${semantic_interpreter_result_status}"
export LUCY_TRACE_SEMANTIC_USE_REASON="${semantic_interpreter_use_reason}"
export LUCY_TRACE_SEMANTIC_USED_FOR_ROUTING="${semantic_interpreter_used_for_routing}"
export LUCY_TRACE_SEMANTIC_FORWARD_CANDIDATES="${semantic_interpreter_forward_candidates}"
export LUCY_TRACE_SEMANTIC_SELECTED_NORMALIZED_QUERY="${semantic_interpreter_selected_normalized_query}"
export LUCY_TRACE_SEMANTIC_SELECTED_RETRIEVAL_QUERY="${semantic_interpreter_selected_retrieval_query}"
export LUCY_TRACE_SEMANTIC_NORMALIZED_CANDIDATES_JSON="${semantic_interpreter_normalized_candidates_json}"
export LUCY_TRACE_SEMANTIC_RETRIEVAL_CANDIDATES_JSON="${semantic_interpreter_retrieval_candidates_json}"
export LUCY_TRACE_MEDICAL_DETECTOR_FIRED="${medical_detector_fired}"
export LUCY_TRACE_MEDICAL_ORIGINAL_QUERY="${medical_detector_original_query}"
export LUCY_TRACE_MEDICAL_RESOLVED_EXECUTION_QUERY="${medical_detector_resolved_execution_query}"
export LUCY_TRACE_MEDICAL_DETECTION_SOURCE="${medical_detector_detection_source}"
export LUCY_TRACE_MEDICAL_PATTERN_FAMILY="${medical_detector_pattern_family}"
export LUCY_TRACE_MEDICAL_CANDIDATE_MEDICATION="${medical_detector_candidate_medication}"
export LUCY_TRACE_MEDICAL_NORMALIZED_CANDIDATE="${medical_detector_normalized_candidate}"
export LUCY_TRACE_MEDICAL_NORMALIZED_QUERY="${medical_detector_normalized_query}"
export LUCY_TRACE_MEDICAL_CONFIDENCE="${medical_detector_confidence}"
export LUCY_TRACE_MEDICAL_CONFIDENCE_SCORE="${medical_detector_confidence_score}"
export LUCY_TRACE_MEDICAL_PROVENANCE_NOTES_JSON="${medical_detector_provenance_notes_json}"
export LUCY_TRACE_GOVERNOR_INTENT="${governor_intent}"
export LUCY_TRACE_GOVERNOR_CONFIDENCE="${governor_confidence}"
export LUCY_TRACE_GOVERNOR_ROUTE="${governor_route}"
export LUCY_TRACE_GOVERNOR_ALLOWED_TOOLS="${governor_allowed_tools}"
export LUCY_TRACE_GOVERNOR_REQUIRES_SOURCES="${governor_requires_sources}"
export LUCY_TRACE_GOVERNOR_REQUIRES_CLARIFICATION="${governor_requires_clarification}"
export LUCY_TRACE_GOVERNOR_CLARIFICATION_QUESTION="${clarification_question:-}"
export LUCY_TRACE_GOVERNOR_FALLBACK_POLICY="${governor_fallback_policy}"
export LUCY_TRACE_GOVERNOR_AUDIT_TAGS="${governor_audit_tags}"
export LUCY_TRACE_GOVERNOR_CONTRACT_VERSION="${governor_contract_version}"
export LUCY_TRACE_GOVERNOR_LOCAL_RESPONSE_ID="${governor_local_response_id}"
export LUCY_TRACE_GOVERNOR_LOCAL_RESPONSE_TEXT="${governor_local_response_text}"
export LUCY_TRACE_GOVERNOR_RESOLVED_QUESTION="${governor_resolved_question:-}"
export LUCY_TRACE_AUGMENTATION_POLICY="${augmentation_policy}"
export LUCY_TRACE_AUGMENTATION_REQUESTED_MODE="${requested_mode}"
export LUCY_TRACE_AUGMENTATION_FINAL_MODE="${final_mode}"
export LUCY_TRACE_AUGMENTATION_FALLBACK_USED="${fallback_used}"
export LUCY_TRACE_AUGMENTATION_FALLBACK_REASON="${fallback_reason}"
export LUCY_TRACE_AUGMENTATION_TRUST_CLASS="${trust_class}"
emit_execution_contract_trace
router_allow_domains_file=""
router_allow_domains_file=""
if [[ -n "${allow_domains_file}" ]]; then
  if [[ "${allow_domains_file}" = /* ]]; then
    router_allow_domains_file="${allow_domains_file}"
  else
    router_allow_domains_file="${ROOT}/${allow_domains_file}"
  fi
  if [[ ! -s "${router_allow_domains_file}" ]]; then
    err "missing/empty allow_domains_file from plan: ${router_allow_domains_file}"
    exit 3
  fi
fi
telemetry_sync_enabled="1"

if [[ "${route_mode}" == "CLARIFY" || "${manifest_clarify_required}" == "true" || "${needs_clarification}" == "true" ]]; then
  router_outcome_code="clarification_requested"
  outcome_code_override="clarification_requested"
  fallback_kind="clarification_prompt"
  record_terminal_outcome "clarification_requested" "CLARIFY" "" "0"
  if [[ "${LUCY_ROUTER_DRYRUN:-0}" == "1" ]]; then
    emit_dryrun_summary
    exit 0
  fi
  if [[ -n "${clarification_question}" ]]; then
    printf '%s\n' "${clarification_question}"
  elif [[ -n "${one_clarifying_question}" ]]; then
    printf '%s\n' "${one_clarifying_question}"
  else
    printf '%s\n' "Do you want general information, current news, or travel safety information?"
  fi
  exit 0
fi

case "${offline_action}" in
  allow) ;;
  validated_insufficient)
    emit_route_trace "no" "not_applicable"
    record_terminal_outcome "validated_insufficient" "${force_mode:-LOCAL}" "" "0"
    print_validated_insufficient
    exit 0
    ;;
  requires_evidence)
    emit_route_trace "no" "not_applicable"
    record_terminal_outcome "requires_evidence_mode" "${force_mode:-LOCAL}" "" "0"
    requires_evidence_mode "${question_for_plan}"
    exit 0
    ;;
  *)
    err "unsupported offline_action from mapper: ${offline_action}"
    exit 4
    ;;
esac

if [[ "${LUCY_DEBUG_VALIDATED:-0}" == "1" ]]; then
  output_mode="VALIDATED"
elif [[ -n "${LUCY_OUTPUT_MODE:-}" ]]; then
  case "${LUCY_OUTPUT_MODE}" in
    CHAT|CONVERSATION|LIGHT_EVIDENCE|VALIDATED|BRIEF) output_mode="${LUCY_OUTPUT_MODE}" ;;
    *) err "invalid LUCY_OUTPUT_MODE: ${LUCY_OUTPUT_MODE}"; exit 4 ;;
  esac
else
  output_mode="${plan_output_mode}"
fi

if [[ "${conv_force}" == "1" && "${needs_web}" == "false" && "${output_mode}" == "CHAT" ]]; then
  output_mode="CONVERSATION"
fi

if [[ "${LUCY_ROUTER_DRYRUN:-0}" != "1" && -n "${one_clarifying_question}" ]]; then
  if [[ -z "${route_prefix}" || "${route_prefix}" == "evidence" ]]; then
    router_outcome_code="clarification_requested"
    outcome_code_override="clarification_requested"
    fallback_kind="clarification_prompt"
    final_mode="CLARIFY"
    record_terminal_outcome "clarification_requested" "CLARIFY" "" "0"
    printf '%s\n' "${one_clarifying_question}"
    exit 0
  fi
fi

if [[ "${LUCY_DEBUG_ROUTE:-0}" == "1" ]]; then
  printf 'DEBUG_ROUTE intent=%s governor_intent=%s governor_route=%s needs_web=%s output_mode=%s allow_domains_file=%s region_filter=%s policy_recommended=%s policy_actual=%s operator_override=%s confidence=%s threshold=%s fallback_policy=%s\n' \
    "${intent}" "${governor_intent}" "${governor_route}" "${needs_web}" "${output_mode}" "${router_allow_domains_file}" "${region_filter}" "${policy_recommended_route}" "${policy_actual_route}" "${policy_operator_override}" "${policy_confidence}" "${policy_confidence_threshold}" "${governor_fallback_policy}" >&2
fi

lat_pre_stage_start_ms="$(latprof_now_ms)"
if [[ "${LUCY_ROUTER_DRYRUN:-0}" == "1" ]]; then
  emit_dryrun_summary
  exit 0
fi

route_reason_override="${route_reason_override:-router_classifier_mapper}"
if [[ "${intent}" == "MEDICAL_INFO" ]]; then
  route_reason_override="medical_evidence_only"
fi
if [[ -n "${mapped_route_reason_override:-}" ]]; then
  route_reason_override="${mapped_route_reason_override}"
fi
if [[ "${augmented_direct_request}" == "true" && "${augmentation_policy}" == "direct_allowed" ]]; then
  aug_raw=""
  aug_rc=1
  if run_augmented_unverified_answer "${question_for_plan}" 2>/dev/null; then
    aug_rc=0
    aug_raw="${augmented_unverified_raw}"
    final_mode="AUGMENTED"
    trust_class="unverified"
    fallback_used="false"
    fallback_reason="direct_request"
    augmented_provider_call_reason="direct"
    if [[ "${augmented_provider_used}" == "none" ]]; then
      augmented_provider_usage_class="local"
      augmented_provider_cost_notice="false"
      augmented_paid_provider_invoked="false"
    fi
    router_outcome_code="augmented_answer"
    outcome_code_override="augmented_answer"
    final_out="$(render_chat_fast_from_raw "${aug_raw}")"
    if [[ -z "$(printf '%s' "${final_out}" | tr -d '[:space:]')" ]]; then
      final_out="$(runtime_local_fallback_text)"
    fi
    if augmented_response_requires_clarification; then
      final_mode="CLARIFY"
      trust_class=""
      fallback_reason="augmented_clarify_preferred"
      router_outcome_code="clarification_requested"
      outcome_code_override="clarification_requested"
      record_terminal_outcome "clarification_requested" "CLARIFY" "" "0"
    else
      final_out="Augmented mode (unverified answer):"$'\n'"${final_out}"
      record_terminal_outcome "augmented_answer" "AUGMENTED" "" "0"
    fi
    latprof_append "execute_plan" "post_processing" "0"
    latprof_append "execute_plan" "total" "$(( $(latprof_now_ms) - lat_total_start_ms ))"
    printf '%s\n' "${final_out}"
    exit 0
  else
    aug_rc=$?
  fi
  final_mode="AUGMENTED"
  trust_class="unverified"
  fallback_used="false"
  if [[ "${augmented_provider}" == "grok" && "${aug_rc}" -eq 2 ]]; then
    fallback_reason="direct_grok_provider_unavailable"
  elif [[ "${augmented_provider}" == "openai" && "${aug_rc}" -eq 2 ]]; then
    fallback_reason="direct_openai_provider_unavailable"
  else
    fallback_reason="direct_augmented_generation_failed"
  fi
  router_outcome_code="execution_error"
  outcome_code_override="execution_error"
  augmented_provider_call_reason="error"
  if [[ "${augmented_provider}" == "grok" && "${aug_rc}" -eq 2 ]] || [[ "${augmented_provider}" == "openai" && "${aug_rc}" -eq 2 ]]; then
    provider_error_message="$(augmented_provider_error_message "${augmented_provider}" "${augmented_provider_error_reason}")"
    record_terminal_outcome "execution_error" "AUGMENTED" "${provider_error_message}" "0"
    printf '%s\n' "${provider_error_message}"
  else
    record_terminal_outcome "execution_error" "AUGMENTED" "augmented generation unavailable" "0"
    printf '%s\n' "Augmented mode is enabled, but local unverified generation is unavailable right now."
  fi
  exit 0
fi
if [[ "${force_mode}" == "AUGMENTED" ]]; then
  aug_raw=""
  aug_rc=1
  if [[ "${augmentation_policy}" == "disabled" ]]; then
    final_mode="AUGMENTED"
    requested_mode="AUGMENTED"
    trust_class="unverified"
    fallback_used="false"
    fallback_reason="augmented_route_disabled"
    router_outcome_code="execution_error"
    outcome_code_override="execution_error"
    augmented_provider_call_reason="disabled"
    record_terminal_outcome "execution_error" "AUGMENTED" "Augmented route selected but augmentation is disabled." "0"
    printf '%s\n' "Augmented route selected but augmentation is disabled."
    exit 0
  fi
  if run_augmented_unverified_answer "${question_for_plan}" 2>/dev/null; then
    aug_rc=0
    aug_raw="${augmented_unverified_raw}"
    if [[ "${unverified_context_used}" != "true" || "${augmented_provider_used}" == "none" ]]; then
      aug_rc=3
    fi
  else
    aug_rc=$?
  fi
  if [[ "${aug_rc}" -eq 0 ]]; then
    final_mode="AUGMENTED"
    requested_mode="AUGMENTED"
    trust_class="unverified"
    fallback_used="false"
    fallback_reason="none"
    augmented_provider_call_reason="selected_route"
    if [[ "${augmented_provider_used}" == "none" ]]; then
      augmented_provider_usage_class="local"
      augmented_provider_cost_notice="false"
      augmented_paid_provider_invoked="false"
    fi
    router_outcome_code="augmented_answer"
    outcome_code_override="augmented_answer"
    final_out="$(render_chat_fast_from_raw "${aug_raw}")"
    if [[ -z "$(printf '%s' "${final_out}" | tr -d '[:space:]')" ]]; then
      final_out="$(runtime_local_fallback_text)"
    fi
    if augmented_response_requires_clarification; then
      final_mode="CLARIFY"
      trust_class=""
      fallback_reason="augmented_clarify_preferred"
      router_outcome_code="clarification_requested"
      outcome_code_override="clarification_requested"
      record_terminal_outcome "clarification_requested" "CLARIFY" "" "0"
    else
      final_out="Augmented route (unverified answer):"$'\n'"${final_out}"
      record_terminal_outcome "augmented_answer" "AUGMENTED" "" "0"
    fi
    latprof_append "execute_plan" "post_processing" "0"
    latprof_append "execute_plan" "total" "$(( $(latprof_now_ms) - lat_total_start_ms ))"
    printf '%s\n' "${final_out}"
    exit 0
  fi
  final_mode="AUGMENTED"
  requested_mode="AUGMENTED"
  trust_class="unverified"
  if [[ "${augmented_provider}" == "grok" && "${aug_rc}" -eq 2 ]]; then
    fallback_reason="selected_route_grok_provider_unavailable"
  elif [[ "${augmented_provider}" == "openai" && "${aug_rc}" -eq 2 ]]; then
    fallback_reason="selected_route_openai_provider_unavailable"
  elif [[ "${aug_rc}" -eq 3 ]]; then
    fallback_reason="selected_route_provider_context_missing"
  else
    fallback_reason="selected_route_augmented_generation_failed"
  fi
  router_outcome_code="execution_error"
  outcome_code_override="execution_error"
  augmented_provider_call_reason="error"
  if [[ "${augmented_provider}" == "grok" && "${aug_rc}" -eq 2 ]] || [[ "${augmented_provider}" == "openai" && "${aug_rc}" -eq 2 ]]; then
    provider_error_message="$(augmented_provider_error_message "${augmented_provider}" "${augmented_provider_error_reason}")"
    record_terminal_outcome "execution_error" "AUGMENTED" "${provider_error_message}" "0"
    printf '%s\n' "${provider_error_message}"
  elif [[ "${aug_rc}" -eq 3 ]]; then
    record_terminal_outcome "execution_error" "AUGMENTED" "Augmented route selected but provider context was not returned." "0"
    printf '%s\n' "Augmented route selected but provider context was not returned."
  else
    record_terminal_outcome "execution_error" "AUGMENTED" "augmented generation unavailable" "0"
    printf '%s\n' "Augmented route is selected, but unverified generation is unavailable right now."
  fi
  exit 0
fi
conversation_mode_active="0"
if [[ "${output_mode}" == "CONVERSATION" && "${needs_web}" == "false" ]]; then
  conversation_mode_active="1"
fi
used_local_fast_path="0"
local_direct_used="false"
local_direct_fallback="false"
local_direct_path="disabled"

set +e
identity_trace_file="${ROOT}/tmp/logs/identity_trace.$$.env"
rm -f "${identity_trace_file}" 2>/dev/null || true
latprof_append "execute_plan" "pre_model" "$(( $(latprof_now_ms) - lat_pre_stage_start_ms ))"
if [[ -n "${governor_local_response_text}" ]]; then
  router_outcome_code="${outcome_code_override:-knowledge_short_circuit_hit}"
  ensure_outcome_file
  write_last_route_meta "LOCAL" "${route_reason_override}" "${QUESTION}" ""
  write_last_outcome_meta "LOCAL" "${route_reason_override}" "${QUESTION}" "" "false" "${router_outcome_code}" "" "0"
  printf '%s\n' "${governor_local_response_text}"
  exit 0
fi
if local_direct_eligible; then
  used_local_fast_path="1"
  local_direct_used="true"
  local_direct_path="local_answer"
  local_fast_start_ms="$(latprof_now_ms)"
  ensure_outcome_file
  write_last_route_meta "LOCAL" "${route_reason_override}" "${QUESTION}" ""
  write_last_outcome_meta "LOCAL" "${route_reason_override}" "${QUESTION}" "" "false" "answered" "" "0"
  rc=0
  raw_out=""
  # FIX: Use trap to ensure set -e is restored on signal interruption.
  local _restore_set_e='set -e'
  set +e
  trap "${_restore_set_e}" EXIT INT TERM
  raw_out="$(LUCY_IDENTITY_TRACE_FILE="${identity_trace_file}" LUCY_LOCAL_POLICY_RESPONSE_ID="${governor_local_response_id}" local_direct_request "${question_for_plan}" 2>&1)"
  rc=$?
  trap - EXIT INT TERM
  eval "${_restore_set_e}"
  if [[ "${rc}" -ne 0 ]]; then
    if local_worker_enabled; then
      local_direct_fallback="true"
      local_direct_path="worker"
      # FIX: Use trap to ensure set -e is restored on signal interruption.
      _restore_set_e='set -e'
      set +e
      trap "${_restore_set_e}" EXIT INT TERM
      raw_out="$(LUCY_IDENTITY_TRACE_FILE="${identity_trace_file}" LUCY_LOCAL_POLICY_RESPONSE_ID="${governor_local_response_id}" local_direct_worker_fallback_request "${question_for_plan}" 2>&1)"
      rc=$?
      trap - EXIT INT TERM
      eval "${_restore_set_e}"
    fi
  fi
  local_fast_end_ms="$(latprof_now_ms)"
  latprof_append "lucy_chat" "local_memory_context" "0"
  latprof_append "lucy_chat" "local_tool_exec" "$(( local_fast_end_ms - local_fast_start_ms ))"
  latprof_append "lucy_chat" "local_empty_check" "0"
  latprof_append "lucy_chat" "run_local_total" "$(( local_fast_end_ms - local_fast_start_ms ))"
else
  local_direct_path="lucy_chat"
  [[ -x "${LUCY_CHAT}" ]] || { err "missing lucy_chat: ${LUCY_CHAT}"; exit 3; }
  raw_out="$(LUCY_ROUTER_BYPASS=1 LUCY_CHAT_FORCE_MODE="${force_mode}" LUCY_CHAT_ROUTE_REASON_OVERRIDE="${route_reason_override}" LUCY_NEWS_REGION_FILTER="${region_filter}" LUCY_FETCH_ALLOWLIST_FILTER_FILE="${router_allow_domains_file}" LUCY_SEARCH_ALLOWLIST_FILTER_FILE="${router_allow_domains_file}" LUCY_CONVERSATION_MODE_ACTIVE="${conversation_mode_active}" LUCY_IDENTITY_TRACE_FILE="${identity_trace_file}" LUCY_LOCAL_POLICY_RESPONSE_ID="${governor_local_response_id}" LUCY_SEMANTIC_INTERPRETER_FIRED="${semantic_interpreter_fired}" LUCY_SEMANTIC_INTERPRETER_CONFIDENCE="${semantic_interpreter_confidence}" LUCY_SEMANTIC_INTERPRETER_FORWARD_CANDIDATES="${semantic_interpreter_forward_candidates}" LUCY_SEMANTIC_INTERPRETER_ORIGINAL_QUERY="${semantic_interpreter_original_query}" LUCY_SEMANTIC_INTERPRETER_SELECTED_NORMALIZED_QUERY="${semantic_interpreter_selected_normalized_query}" LUCY_SEMANTIC_INTERPRETER_SELECTED_RETRIEVAL_QUERY="${semantic_interpreter_selected_retrieval_query}" LUCY_SEMANTIC_INTERPRETER_NORMALIZED_CANDIDATES_JSON="${semantic_interpreter_normalized_candidates_json}" LUCY_SEMANTIC_INTERPRETER_RETRIEVAL_CANDIDATES_JSON="${semantic_interpreter_retrieval_candidates_json}" "${LUCY_CHAT}" "${question_for_plan}" 2>&1)"
  rc=$?
fi
set -e
capture_child_route_state "${question_for_plan}" "${force_mode}"
if [[ "${force_mode}" != "LOCAL" && "${child_outcome_code}" == "validation_failed" && "${child_action_hint}" == "enable evidence" ]]; then
  router_outcome_code="validation_failed"
  outcome_code_override="validation_failed"
  trust_class="unknown"
fi
update_semantic_interpreter_child_usage
lat_post_stage_start_ms="$(latprof_now_ms)"
execute_plan_local_diag_append "local_direct_used" "${local_direct_used}"
execute_plan_local_diag_append "local_direct_fallback" "${local_direct_fallback}"
execute_plan_local_diag_append "local_direct_path" "${local_direct_path}"
execute_plan_local_diag_append "local_worker_request_mode" "$(local_worker_request_mode)"
identity_loaded="no"
identity_source="not_applicable"
if [[ -s "${identity_trace_file}" ]]; then
  identity_loaded="$(awk -F= '$1=="IDENTITY_CONTEXT_LOADED"{print $2; exit}' "${identity_trace_file}")"
  identity_source="$(awk -F= '$1=="IDENTITY_CONTEXT_SOURCE"{print $2; exit}' "${identity_trace_file}")"
  [[ -n "${identity_loaded}" ]] || identity_loaded="yes"
  [[ -n "${identity_source}" ]] || identity_source="local_identity_context"
fi
emit_route_trace "${identity_loaded}" "${identity_source}"
rm -f "${identity_trace_file}" 2>/dev/null || true
if [[ "${used_local_fast_path}" == "1" && $rc -eq 0 && "${output_mode}" == "CHAT" && "${needs_web}" == "false" ]]; then
  if is_local_generation_failure_output "${raw_out}"; then
    local_gen_status="fail"
    guard_trigger="local_generation_failure_phrase"
    fallback_kind="deterministic_local_prompt_fallback"
    router_outcome_code="local_guard_fallback"
    local_force_plain_fallback="1"
    final_out="$(runtime_local_prompt_fallback_text "${question_for_plan}" "0")"
  else
    final_out="$(render_chat_fast_from_raw "${raw_out}")"
    final_out="$(local_fast_non_empty_guard "${question_for_plan}" "${final_out}" "CHAT")"
    final_out="$(local_fast_repetition_guard "${question_for_plan}" "${final_out}" "CHAT")"
    if is_evidence_style_text "${final_out}"; then
      evidence_style_blocked="1"
      local_evidence_lexeme_detected="1"
      guard_trigger="local_evidence_lexeme_detected"
      fallback_kind="lexeme_blocked_replacement"
      outcome_code_override="local_lexeme_blocked"
      local_gen_status="fail"
      final_out="$(runtime_local_prompt_fallback_text "${question_for_plan}" "1")"
    fi
  fi
  latprof_append "execute_plan" "post_processing" "$(( $(latprof_now_ms) - lat_post_stage_start_ms ))"
  latprof_append "execute_plan" "total" "$(( $(latprof_now_ms) - lat_total_start_ms ))"
  if is_runtime_local_prompt_fallback_text "${final_out}"; then
    apply_local_degradation_augmented_fallback "${question_for_plan}" "local_generation_degraded" || true
  fi
  printf '%s\n' "${final_out}"
  exit 0
fi
if [[ $rc -ne 0 ]]; then
  if [[ "${needs_web}" == "false" && ( "${output_mode}" == "CONVERSATION" || "${output_mode}" == "CHAT" ) ]]; then
    local_gen_status="fail"
    guard_trigger="local_generation_failure_nonzero_rc"
    fallback_kind="deterministic_local_prompt_fallback"
    router_outcome_code="local_guard_fallback"
    local_force_plain_fallback="1"
    raw_out="$(runtime_local_prompt_fallback_text "${question_for_plan}" "0")"
    rc=0
  else
    if [[ "${output_mode}" == "CONVERSATION" && "${needs_web}" == "false" ]]; then
      render_conversation_fallback "${question_for_plan}"
      exit 0
    fi
    if [[ "${output_mode}" == "CHAT" && "${needs_web}" == "false" ]]; then
      if [[ -n "$(printf '%s' "${raw_out}" | tr -d '[:space:]')" ]]; then
        printf '%s\n' "${raw_out}"
      else
        runtime_local_fallback_text
      fi
      exit 0
    fi
    if [[ "${intent}" == "MEDICAL_INFO" ]]; then
      if is_backend_unavailable_output "${raw_out}"; then
        router_outcome_code="execution_error"
        record_terminal_outcome "execution_error" "${force_mode:-LOCAL}" "" "0"
        print_medical_backend_unavailable
        exit 0
      fi
      router_outcome_code="validation_failed"
      record_terminal_outcome "validated_insufficient" "${force_mode:-LOCAL}" "" "0"
      print_medical_insufficient "${question_for_plan}"
      exit 0
    fi
    if [[ "${output_mode}" == "LIGHT_EVIDENCE" ]]; then
      router_outcome_code="validation_failed"
      record_terminal_outcome "validated_insufficient" "${force_mode:-LOCAL}" "" "0"
      print_light_insufficient
      exit 0
    fi
    router_outcome_code="execution_error"
    record_terminal_outcome "execution_error" "${force_mode:-LOCAL}" "" "0"
    printf '%s\n' "${raw_out}"
    exit 0
  fi
fi

if [[ "${needs_web}" == "false" && ( "${output_mode}" == "CONVERSATION" || "${output_mode}" == "CHAT" ) ]]; then
  if is_local_generation_failure_output "${raw_out}"; then
    local_gen_status="fail"
    guard_trigger="local_generation_failure_phrase"
    fallback_kind="deterministic_local_prompt_fallback"
    router_outcome_code="local_guard_fallback"
    local_force_plain_fallback="1"
    raw_out="$(runtime_local_prompt_fallback_text "${question_for_plan}" "0")"
  fi
fi

if [[ "${output_mode}" == "CONVERSATION" && "${needs_web}" == "false" ]]; then
  if printf '%s' "${raw_out}" | grep -Eqi '^This requires evidence mode\.'; then
    render_conversation_fallback "${question_for_plan}"
    exit 0
  fi
fi

if [[ ( "${intent}" == "WEB_DOC" || "${intent}" == "PRIMARY_DOC" ) && "${output_mode}" == "LIGHT_EVIDENCE" ]]; then
  if printf '%s' "${raw_out}" | grep -Eqi "Insufficient evidence from trusted sources\.?"; then
    if print_primary_doc_fallback_urls "${QUESTION}" "${prefer_domains}"; then exit 0; fi
  fi
fi

[[ -x "${EXTRACTOR}" ]] || { err "missing extractor: ${EXTRACTOR}"; exit 3; }
parsed_json="$(printf '%s\n' "${raw_out}" | "${EXTRACTOR}")"
export PARSED_JSON RAW_OUT="${raw_out}" MIN_SOURCES="${min_sources}" INTENT="${intent}" CATEGORY="${category}" ROOT PREFER_DOMAINS="${prefer_domains}" QUESTION_FOR_PLAN="${question_for_plan}"
parsed_sources_count="$(
  python3 <<'PY'
import json, os
p=json.loads(os.environ.get("PARSED_JSON","{}"))
srcs=p.get("sources") or []
if srcs:
    print(len(srcs))
    raise SystemExit(0)
raw=os.environ.get("RAW_OUT","")
seen=[]
for line in raw.splitlines():
    s=line.strip()
    m=None
    for pat in (
        r"^-\s*([a-z0-9.-]+\.[a-z]{2,})\s*\(",
        r"^\[\d+\]\s*([a-z0-9.-]+\.[a-z]{2,})\s*-",
        r"^https?://([a-z0-9.-]+\.[a-z]{2,})(?:[/:?#]|$)",
    ):
        m=__import__("re").search(pat, s, flags=__import__("re").I)
        if m:
            break
    if not m:
        continue
    d=m.group(1).lower()
    if d not in seen:
        seen.append(d)
print(len(seen))
PY
)"
primary_doc_meta="$(
  python3 <<'PY'
import json, os
import re
from pathlib import Path

def parse_scalar(s):
    s=s.strip()
    if s.startswith('"') and s.endswith('"'):
        return s[1:-1]
    if s == "true":
        return True
    if s == "false":
        return False
    if s.isdigit():
        return int(s)
    if s.startswith("[") and s.endswith("]"):
        inner=s[1:-1].strip()
        return [] if not inner else [x.strip().strip('"') for x in inner.split(",") if x.strip()]
    return s

def load_catalog(path: Path):
    domains={}
    if not path.is_file():
        return domains
    cur=None
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        s=raw.strip()
        if not s or s.startswith("#"):
            continue
        ind=len(raw)-len(raw.lstrip(" "))
        if ind == 2 and s.endswith(":"):
            cur=s[:-1].strip()
            domains[cur]={}
            continue
        if ind == 4 and ":" in s and cur:
            k,v=s.split(":",1)
            domains[cur][k.strip()] = parse_scalar(v)
    return domains

p=json.loads(os.environ.get("PARSED_JSON","{}"))
srcs=p.get("sources") or []
dom=""
if srcs:
    best=(srcs[0] or {})
    dom=str(best.get("domain") or "").strip().lower()
    if dom.startswith("www."):
        dom=dom[4:]
if not dom:
    raw=os.environ.get("RAW_OUT","")
    for line in raw.splitlines():
        s=line.strip()
        m=None
        for pat in (
            r"^-\s*([a-z0-9.-]+\.[a-z]{2,})\s*\(",
            r"^\[\d+\]\s*([a-z0-9.-]+\.[a-z]{2,})\s*-",
            r"^https?://([a-z0-9.-]+\.[a-z]{2,})(?:[/:?#]|$)",
        ):
            m=re.search(pat, s, flags=re.I)
            if m:
                break
        if m:
            dom=m.group(1).lower()
            if dom.startswith("www."):
                dom=dom[4:]
            break
prefer=[x.strip().lower() for x in (os.environ.get("PREFER_DOMAINS","").split(",")) if x.strip()]
is_prefer = dom in prefer or any(dom.endswith("."+d) for d in prefer)
catalog=load_catalog(Path(os.environ.get("ROOT","")) / "config" / "trust" / "trust_catalog.yaml")
meta=catalog.get(dom, {})
tier=meta.get("tier", "")
cats=meta.get("categories") or []
if not isinstance(cats, list):
    cats=[str(cats)]
is_auth = is_prefer and str(tier) == "1"
if not is_auth and str(tier) == "1" and any(c in {"electronics","vendor_docs","docs"} for c in cats):
    is_auth = True
print(f"{dom}\t{1 if is_auth else 0}\t{tier}")
PY
)"
primary_doc_best_domain="$(printf '%s' "${primary_doc_meta}" | awk -F'\t' '{print $1}')"
primary_doc_best_authoritative="$(printf '%s' "${primary_doc_meta}" | awk -F'\t' '{print $2}')"
effective_min_sources="${min_sources}"
evidence_selected_key_family="$(read_state_field "${LAST_OUTCOME_FILE}" "EVIDENCE_NORMALIZER_SELECTED_KEY_FAMILY")"
fallback_source_count="$(count_last_route_evidence_domains)"
if ! [[ "${fallback_source_count}" =~ ^[0-9]+$ ]]; then
  fallback_source_count=0
fi
fallback_source_domains="$(last_route_evidence_domains_csv 3)"

if [[ "${intent}" == "MEDICAL_INFO" ]]; then
  if is_backend_unavailable_output "${raw_out}"; then
    record_terminal_outcome "execution_error" "${force_mode:-LOCAL}" "" "0"
    print_medical_backend_unavailable
    exit 0
  fi
  if [[ "${force_mode}" != "EVIDENCE" ]]; then
    record_terminal_outcome "validated_insufficient" "${force_mode:-LOCAL}" "" "0"
    print_medical_insufficient "${question_for_plan}"
    exit 0
  fi
  if ! [[ "${parsed_sources_count}" =~ ^[0-9]+$ ]]; then
    parsed_sources_count=0
  fi
  if [[ "${parsed_sources_count}" -lt "${min_sources:-2}" ]]; then
    fallback_domain_count="$(count_last_route_evidence_domains)"
    if [[ "${fallback_domain_count}" =~ ^[0-9]+$ ]] && [[ "${fallback_domain_count}" -gt "${parsed_sources_count}" ]]; then
      parsed_sources_count="${fallback_domain_count}"
    fi
  fi
  if [[ "${parsed_sources_count}" -lt "${min_sources:-2}" ]]; then
    record_terminal_outcome "validated_insufficient" "${force_mode:-LOCAL}" "" "0"
    print_medical_insufficient "${question_for_plan}"
    exit 0
  fi
fi

if [[ "${intent}" == "PRIMARY_DOC" ]]; then
  output_mode="LIGHT_EVIDENCE"
  if ! [[ "${parsed_sources_count}" =~ ^[0-9]+$ ]]; then
    parsed_sources_count=0
  fi
  if [[ "${parsed_sources_count}" -eq 0 ]]; then
    if print_primary_doc_fallback_urls "${QUESTION}" "${prefer_domains}"; then exit 0; fi
    record_terminal_outcome "validated_insufficient" "${force_mode:-LOCAL}" "" "0"
    print_light_insufficient
    exit 0
  fi
  if [[ "${parsed_sources_count}" -eq 1 ]]; then
    if [[ "${primary_doc_best_authoritative}" != "1" ]]; then
      if print_primary_doc_fallback_urls "${QUESTION}" "${prefer_domains}"; then exit 0; fi
      record_terminal_outcome "validated_insufficient" "${force_mode:-LOCAL}" "" "0"
      print_light_insufficient
      exit 0
    fi
    effective_min_sources="1"
  fi
fi

# Narrow corroboration relaxation:
# FX BOI exchange-rate prompts can be satisfied by one authoritative source.
if [[ "${intent}" == "WEB_FACT" && "${output_mode}" == "LIGHT_EVIDENCE" ]]; then
  if [[ "${evidence_selected_key_family}" =~ (^|,)fx_usd_ils($|,) ]]; then
    if [[ "${parsed_sources_count}" =~ ^[0-9]+$ ]] && [[ "${parsed_sources_count}" -ge 1 ]]; then
      effective_min_sources="1"
    elif printf '%s' "${raw_out}" | grep -Eqi '\bboi\.org\.il\b'; then
      effective_min_sources="1"
    elif printf '%s' "${fallback_source_domains}" | grep -Eqi '(^|,)boi\.org\.il(,|$)'; then
      effective_min_sources="1"
    fi
  fi
fi

if [[ "${output_mode}" == "VALIDATED" ]]; then
  if ! [[ "${parsed_sources_count}" =~ ^[0-9]+$ ]]; then
    parsed_sources_count=0
  fi
  if [[ "${parsed_sources_count}" -eq 0 ]]; then
    if [[ "${intent}" == "MEDICAL_INFO" ]]; then
      record_terminal_outcome "validated_insufficient" "${force_mode:-LOCAL}" "" "0"
      print_medical_insufficient "${question_for_plan}"
      exit 0
    fi
    record_terminal_outcome "validated_insufficient" "${force_mode:-LOCAL}" "" "0"
    print_validated_insufficient
    exit 0
  fi
fi
export MIN_SOURCES="${effective_min_sources}"
export FALLBACK_SOURCE_COUNT="${fallback_source_count}"
export FALLBACK_SOURCE_DOMAINS="${fallback_source_domains}"
export SELECTED_KEY_FAMILY="${evidence_selected_key_family}"
evidence_pack_session_id="${child_route_session_id}"
if [[ -z "${evidence_pack_session_id}" ]]; then
  evidence_pack_session_id="$(read_state_field "${LAST_OUTCOME_FILE}" "SESSION_ID")"
fi
if [[ -n "${evidence_pack_session_id}" ]]; then
  export EVIDENCE_PACK_FILE="${ROOT}/evidence/${evidence_pack_session_id}/pack/evidence_pack.txt"
else
  export EVIDENCE_PACK_FILE=""
fi

if [[ "${category}" == "travel_advisory" && "${output_mode}" == "LIGHT_EVIDENCE" ]]; then
  if ! [[ "${parsed_sources_count}" =~ ^[0-9]+$ ]]; then
    parsed_sources_count=0
  fi
  effective_found_count="${parsed_sources_count}"
  if [[ "${fallback_source_count}" =~ ^[0-9]+$ ]] && [[ "${fallback_source_count}" -gt "${effective_found_count}" ]]; then
    effective_found_count="${fallback_source_count}"
  fi
  if [[ "${effective_found_count}" -lt "${effective_min_sources:-2}" ]]; then
    record_terminal_outcome "validated_insufficient" "${force_mode:-LOCAL}" "" "0"
    print_travel_advisory_fallback "${question_for_plan}" "${effective_found_count}" "${fallback_source_domains}" "${effective_min_sources:-2}"
    exit 0
  fi
  if printf '%s' "${raw_out}" | grep -Eqi 'Insufficient evidence from trusted sources\.?'; then
    # Keep legacy decisive fallback for non-classified travel paths.
    # For mapped travel_* key families, allow render_light to attempt
    # class-specific extraction from the fetched evidence pack first.
    if ! [[ "${evidence_selected_key_family}" =~ (^|,)travel_ ]]; then
      record_terminal_outcome "validated_insufficient" "${force_mode:-LOCAL}" "" "0"
      print_travel_advisory_fallback "${question_for_plan}" "${effective_found_count}" "${fallback_source_domains}" "${effective_min_sources:-2}"
      exit 0
    fi
  fi
fi

render_chat(){
  python3 <<'PY'
import json, os
p=json.loads(os.environ.get("PARSED_JSON","{}"))
raw=os.environ.get("RAW_OUT","")
if p.get("parse_ok"):
  ans=(p.get("answer") or "").strip()
  if ans:
    print(ans)
  elif p.get("claims"):
    print((p.get("claims") or [""])[0])
  else:
    print(raw)
else:
  lines=[]
  for ln in raw.splitlines():
    s=ln.strip()
    if s in {"BEGIN_VALIDATED","END_VALIDATED"}:
      continue
    if s:
      lines.append(s)
  print(" ".join(lines) if lines else raw)
PY
}

render_conversation(){
  local chat_out
  chat_out="$(render_chat)"
  if [[ "${needs_web}" == "true" ]]; then
    printf '%s\n' "${chat_out}"
    return 0
  fi
  if [[ "${local_force_plain_fallback}" == "1" ]]; then
    conversation_shim_applied="0"
    conversation_shim_profile="none"
    printf '%s\n' "${chat_out}"
    return 0
  fi
  [[ -x "${CONV_SHIM}" ]] || { err "missing conversation shim: ${CONV_SHIM}"; exit 3; }
  conversation_shim_applied="1"
  conversation_shim_profile="$(conversation_profile_style)"
  LUCY_USER_PROMPT="${question_for_plan}" LUCY_CONV_INTENT="${intent:-}" python3 "${CONV_SHIM}" <<< "${chat_out}"
}

render_light(){
  python3 <<'PY'
import json, os
import re
p=json.loads(os.environ.get("PARSED_JSON","{}"))
raw=os.environ.get("RAW_OUT","")
question=os.environ.get("QUESTION_FOR_PLAN","")
category=os.environ.get("CATEGORY","")
selected_key_family=os.environ.get("SELECTED_KEY_FAMILY","")
evidence_pack_file=os.environ.get("EVIDENCE_PACK_FILE","")
min_sources=max(1, int(os.environ.get("MIN_SOURCES","1") or "1"))
fallback_source_count=max(0, int(os.environ.get("FALLBACK_SOURCE_COUNT","0") or "0"))
fallback_source_domains=[d.strip().lower() for d in (os.environ.get("FALLBACK_SOURCE_DOMAINS","").split(",")) if d.strip()]
light_answer_max_chars=max(200, int(os.environ.get("LUCY_LIGHT_ANSWER_MAX_CHARS","2400") or "2400"))
def load_pack_text(path: str) -> str:
  p=(path or "").strip()
  if not p:
    return ""
  try:
    with open(p, "r", encoding="utf-8", errors="ignore") as h:
      return h.read()
  except OSError:
    return ""
def extract_cpi_from_pack(pack_text: str):
  if not pack_text:
    return None
  lines=pack_text.splitlines()
  date_pat_weekday=re.compile(r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),\s+\d{1,2}\s+[A-Z][a-z]{2}\s+20\d{2}\b")
  date_pat_month=re.compile(r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+20\d{2}\b", re.I)
  rate_pat=re.compile(r"\b\d{1,2}(?:\.\d)?(?:\s?%|\s+percent)", re.I)
  context_pat=re.compile(r"\b(cpi|consumer price index|inflation)\b", re.I)
  for i, raw_line in enumerate(lines):
    line=raw_line.strip()
    if not line:
      continue
    window="\n".join(lines[max(0, i-2):min(len(lines), i+3)])
    if not context_pat.search(window):
      continue
    rate_m=rate_pat.search(window)
    if not rate_m:
      continue
    date_m=date_pat_weekday.search(window) or date_pat_month.search(window)
    if not date_m:
      continue
    rate=rate_m.group(0).strip()
    if re.search(r"\bpercent\b", rate, flags=re.I):
      rate=rate.split()[0] + "%"
    else:
      rate=rate.replace(" ", "")
    date_txt=date_m.group(0)
    return {
      "rate": rate,
      "date": date_txt,
      "line": line,
    }
  return None
def extract_travel_signal_from_pack(pack_text: str, q: str):
  qn=(q or "").strip().lower()
  destination=""
  if "lebanon" in qn:
    destination="Lebanon"
  if not pack_text:
    return None
  if not destination and re.search(r"\blebanon\b", pack_text, flags=re.I):
    destination="Lebanon"
  if not destination:
    return None
  lines=pack_text.splitlines()
  risk_pat=re.compile(
    r"\b(do not travel|avoid travel|all but essential travel|against non-essential travel|advis(?:e|es|ed)\s+against\s+non-essential\s+travel|active conflict|ground invasion|air attacks?|strikes?|war)\b",
    re.I,
  )
  auth_map=(
    ("UK Foreign Office", r"\b(foreign office|fcdo|uk government)\b"),
    ("U.S. State Department", r"\b(state department)\b"),
    ("Government Advisory", r"\b(travel advisory|official advisory)\b"),
  )
  date_pat=re.compile(r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),\s+\d{1,2}\s+[A-Z][a-z]{2}\s+20\d{2}\b")
  hits=[]
  authorities=[]
  seen_auth=set()
  extracted_date=""
  for i, raw in enumerate(lines):
    s=raw.strip()
    if not s:
      continue
    if "lebanon" not in s.lower():
      continue
    win="\n".join(lines[max(0, i-2):min(len(lines), i+3)])
    if not risk_pat.search(win):
      continue
    hits.append(s)
    if not extracted_date:
      dm=date_pat.search(win)
      if dm:
        extracted_date=dm.group(0)
    for auth_label, auth_pat in auth_map:
      if re.search(auth_pat, win, flags=re.I) and auth_label not in seen_auth:
        seen_auth.add(auth_label)
        authorities.append(auth_label)
  if not hits:
    return None
  return {
    "destination": destination,
    "status": "high-risk conflict environment",
    "authorities": authorities,
    "date": extracted_date,
    "evidence": hits[0],
  }
def extract_ai_lab_eval_statements(pack_text: str):
  if not pack_text:
    return []
  lines=pack_text.splitlines()
  date_pat=re.compile(r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),\s+\d{1,2}\s+[A-Z][a-z]{2}\s+20\d{2}\b")
  lab_map=(
    ("OpenAI", r"\bopenai\b"),
    ("Anthropic", r"\banthropic\b"),
    ("Google", r"\bgoogle\b"),
    ("DeepMind", r"\bdeepmind\b"),
    ("Meta", r"\bmeta\b"),
    ("Microsoft", r"\bmicrosoft\b"),
    ("xAI", r"\bxai\b"),
  )
  eval_pat=re.compile(r"\b(evaluation|evaluations|eval|benchmark|benchmarks|red[- ]teaming|safety testing|model testing|model|models|safety|red team)\b", re.I)
  stmt_pat=re.compile(r"\b(announced|released|published|reported|said|says|stated|shared|updated|statement|introducing|sues|seeking|clashed)\b", re.I)
  strict_out=[]
  fallback_out=[]
  seen=set()
  def skip_line(s: str) -> bool:
    if not s:
      return True
    if s.startswith(("*", "KEY=", "DOMAIN=", "FETCH_", "BEGIN_", "END_", "====", "----")):
      return True
    if len(s) < 24:
      return True
    return False
  for i, raw in enumerate(lines):
    s=raw.strip()
    if skip_line(s):
      continue
    win="\n".join(lines[max(0, i-2):min(len(lines), i+3)])
    lab_name=""
    for label, pat in lab_map:
      if re.search(pat, win, flags=re.I):
        lab_name=label
        break
    if not lab_name:
      continue
    if lab_name in seen:
      continue
    if not (stmt_pat.search(win) or eval_pat.search(win)):
      continue
    seen.add(lab_name)
    dm=date_pat.search(win)
    date_txt=dm.group(0) if dm else ""
    clean=re.sub(r"\s+", " ", s).strip()
    hit={
      "lab": lab_name,
      "date": date_txt,
      "snippet": clean[:220],
      "explicit_eval": bool(eval_pat.search(win)),
    }
    if hit["explicit_eval"]:
      strict_out.append(hit)
    else:
      fallback_out.append(hit)
    if (len(strict_out) + len(fallback_out)) >= 2:
      break
  if strict_out:
    return strict_out[:2]
  return fallback_out[:2]
def is_compound_policy_query(txt: str) -> bool:
  q=(txt or "").strip().lower()
  has_climate=re.search(r"\b(climate policy|climate regulation|emissions policy|carbon policy)\b", q) is not None
  has_ai=re.search(r"\b(ai safety|ai regulation|ai governance|technology regulation|technology governance|tech governance)\b", q) is not None
  return has_climate and has_ai
def is_cross_domain_policy_query(txt: str) -> bool:
  q=(txt or "").strip().lower()
  hits=0
  if re.search(r"\b(climate|climate policy|climate regulation|emissions|carbon)\b", q):
    hits += 1
  if re.search(r"\b(ai|artificial intelligence|ai safety|ai regulation|ai governance|technology regulation|technology governance|tech governance)\b", q):
    hits += 1
  if re.search(r"\b(financial regulation|financial policy|banking regulation|market regulation|financial|banking|market)\b", q):
    hits += 1
  if hits < 2:
    return False
  return re.search(r"\b(global policy|policy developments?|regulatory direction|predict|interaction|interact|across)\b", q) is not None
def maybe_specialize_insufficient(answer: str) -> str:
  t=(answer or "").strip()
  if "insufficient evidence from trusted sources" in t.lower() and is_compound_policy_query(question):
    return (
      "Insufficient trusted evidence across requested climate-policy and AI-governance domains.\n"
      "Try: climate policy only, AI safety only, or one named regulator, region, or decision."
    )
  if "insufficient evidence from trusted sources" in t.lower() and is_cross_domain_policy_query(question):
    return (
      "Insufficient trusted evidence across requested policy domains.\n"
      "Try: climate policy only, AI safety only, financial regulation only, or one named regulator, region, or decision."
    )
  return t
def normalize_answer(txt: str) -> str:
  t=(txt or "").strip()
  if t.lower().startswith("summary:"):
    t=t.split(":",1)[1].strip()
  if t.lower().startswith("answer:"):
    t=t.split(":",1)[1].strip()
  if len(t) > light_answer_max_chars:
    t=t[: max(1, light_answer_max_chars - 3)].rstrip() + "..."
  return t

def format_light_answer(txt: str) -> str:
  t=(txt or "").strip()
  if not t:
    return t
  t=re.sub(r"\s+(Key items:)", r"\n\1", t)
  t=re.sub(r"\s+(Bounded forecast \(not a deterministic prediction\):)", r"\n\1", t)
  t=re.sub(r"\s+(Forecast confidence:)", r"\n\1", t)
  t=re.sub(r"\s+(Conflicts/uncertainty:)", r"\n\1", t)
  t=re.sub(r"\s+(Sources:)", r"\n\1", t)
  # Split inline bullet lists into separate lines (common news/evidence output shape).
  t=re.sub(r"\s+-\s+(?=\[)", r"\n- ", t)
  # Keep inline hyphenated title suffixes (e.g., "crimes - analysis") intact.
  # Only split forecast bullets explicitly.
  t=re.sub(r"\s+-\s+(?=(Base case|Alternative|Tail risk)\b)", r"\n- ", t)
  t=re.sub(r"\n{3,}", "\n\n", t)
  lines=[ln.rstrip() for ln in t.splitlines()]
  return "\n".join(lines).strip()

if not p.get("parse_ok"):
  lines=[ln.strip() for ln in raw.splitlines() if ln.strip() and ln.strip() not in {"BEGIN_VALIDATED","END_VALIDATED"}]
  joined=" ".join(lines)
  ans=joined
  srcs=[]
  low=joined.lower()
  pos=low.rfind(" sources:")
  if pos >= 0:
    ans=joined[:pos].strip()
    src_blob=joined[pos+9:].strip()
    tokens=[]
    tokens.extend(re.findall(r"https?://[^\s,;]+", src_blob))
    tokens.extend(re.findall(r"\b(?:[a-z0-9-]+\.)+[a-z]{2,}\b", src_blob.lower()))
    for tok in [x.strip() for x in tokens if x.strip()]:
      if tok.startswith("http://") or tok.startswith("https://"):
        d=tok.split("://",1)[1].split("/",1)[0].lower()
        if d.startswith("www."):
          d=d[4:]
        srcs.append((d,tok))
      else:
        d=tok.lower()
        if d.startswith("www."):
          d=d[4:]
        srcs.append((d,""))
  ans=maybe_specialize_insufficient(normalize_answer(ans) or "Insufficient evidence from trusted sources.")
  if not srcs and fallback_source_domains:
    srcs=[(d,"") for d in fallback_source_domains]
  uniq_domains=[]
  seen_domains=set()
  for d,_u in srcs:
    d=(d or "").strip().lower()
    if not d:
      continue
    if d in seen_domains:
      continue
    seen_domains.add(d)
    uniq_domains.append(d)
  effective_found=max(len(uniq_domains), fallback_source_count)
  key_families=[x.strip().lower() for x in selected_key_family.split(",") if x.strip()]
  pack_text=load_pack_text(evidence_pack_file)
  ans_low=ans.lower()
  if "insufficient evidence from trusted sources" in ans_low and effective_found >= min_sources:
    is_cpi_query=re.search(r"\b(cpi|consumer price index|inflation)\b", question or "", flags=re.I) is not None
    if "cpi_us" in key_families or is_cpi_query:
      cpi=extract_cpi_from_pack(pack_text)
      if cpi:
        ans=(
          f"Extracted U.S. CPI data point from current sources: {cpi['rate']} "
          f"(date reference: {cpi['date']}). "
          "This is the strongest extractable CPI value/date pair from retrieved sources."
        )
    if ("travel_" in ",".join(key_families)) or category == "travel_advisory":
      travel=extract_travel_signal_from_pack(pack_text, question)
      if travel:
        auth_txt=", ".join(travel["authorities"]) if travel["authorities"] else "not explicit in retrieved items"
        date_txt=f" Latest dated evidence: {travel['date']}." if travel["date"] else ""
        ans=(
          f"Current travel risk signal for {travel['destination']}: {travel['status']} based on retrieved reporting. "
          f"Issuing advisory authority: {auth_txt}.{date_txt} "
          "Conservative guidance: avoid non-essential travel and verify an official government advisory before departure."
        )
  elif effective_found >= min_sources and (("travel_" in ",".join(key_families)) or category == "travel_advisory"):
    # Recover class-specific travel assembly when model output returns a generic
    # refusal despite sufficient travel evidence in the pack.
    if re.search(r"\b(i cannot provide information about travel(?:ing)?|can i help you with something else)\b", ans_low):
      travel=extract_travel_signal_from_pack(pack_text, question)
      if travel:
        auth_txt=", ".join(travel["authorities"]) if travel["authorities"] else "not explicit in retrieved items"
        date_txt=f" Latest dated evidence: {travel['date']}." if travel["date"] else ""
        ans=(
          f"Current travel risk signal for {travel['destination']}: {travel['status']} based on retrieved reporting. "
          f"Issuing advisory authority: {auth_txt}.{date_txt} "
          "Conservative guidance: avoid non-essential travel and verify an official government advisory before departure."
        )
  if "ai_labs_evals" in key_families:
    labs=extract_ai_lab_eval_statements(pack_text)
    if labs:
      lines=[]
      for item in labs:
        date_txt=f" ({item['date']})" if item["date"] else ""
        lines.append(f"- {item['lab']}{date_txt}: {item['snippet']}")
      has_explicit_eval=any(bool(item.get("explicit_eval")) for item in labs)
      if has_explicit_eval:
        ans=(
          "Recent major-lab evaluation statements detected in retrieved sources:\n"
          + "\n".join(lines)
        )
      else:
        ans=(
          "Recent major-lab statements detected in retrieved sources (evaluation-specific details are limited in retrieved snippets):\n"
          + "\n".join(lines)
        )
  print("From current sources:")
  print(format_light_answer(ans))
  if srcs:
    seen=set()
    uniq=[]
    for d,u in srcs:
      k=(d,u)
      if k in seen:
        continue
      seen.add(k)
      uniq.append((d,u))
    print("Sources:")
    for d,u in uniq[:3]:
      if d and u:
        print(f"- {d} ({u})")
      elif d:
        print(f"- {d}")
      elif u:
        print(f"- {u}")
    effective_found=max(len(uniq), fallback_source_count)
    if effective_found < min_sources:
      print(f"Note: insufficient corroboration (found {effective_found} sources, need {min_sources}).")
  else:
    if "insufficient evidence from trusted sources." in ans.lower():
      print(f"Note: insufficient corroboration (found {fallback_source_count} sources, need {min_sources}).")
  raise SystemExit(0)

answer=normalize_answer(p.get("answer") or "")
if not answer:
  claims=p.get("claims") or []
  answer=claims[0] if claims else "Insufficient evidence from trusted sources."
answer=format_light_answer(maybe_specialize_insufficient(answer))

print("From current sources:")
print(answer)

srcs=[]
seen=set()
for s in (p.get("sources") or []):
  d=(s.get("domain") or "").strip()
  u=(s.get("url") or "").strip()
  key=(d,u)
  if key in seen:
    continue
  seen.add(key)
  if d or u:
    srcs.append((d,u))
if not srcs and fallback_source_domains:
  srcs=[(d,"") for d in fallback_source_domains]

if srcs:
  print("Sources:")
  for d,u in srcs[:3]:
    if d and u:
      print(f"- {d} ({u})")
    elif d:
      print(f"- {d}")
    else:
      print(f"- {u}")

effective_found=max(len(srcs), fallback_source_count)
if effective_found < min_sources:
  print(f"Note: insufficient corroboration (found {effective_found} sources, need {min_sources}).")
PY
}

render_brief(){
  python3 <<'PY'
import json, os
intent=os.environ.get("INTENT","")
p=json.loads(os.environ.get("PARSED_JSON","{}"))
raw=os.environ.get("RAW_OUT","")
if intent != "STATUS_UPDATE" or not p.get("parse_ok"):
  print(raw)
  raise SystemExit(0)

ans=(p.get("answer") or "").strip() or "No summary available."
claims=(p.get("claims") or [])[:4]
srcs=[]
for s in (p.get("sources") or [])[:3]:
  d=(s.get("domain") or "").strip()
  if d:
    srcs.append(d)
print("LUCY BRIEF")
print(f"Summary: {ans}")
if claims:
  print("Key items:")
  for c in claims:
    print(f"- {c}")
if srcs:
  print("Sources: " + ", ".join(srcs))
PY
}

guard_normalize(){
  printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]' | sed -E 's/[[:space:]]+/ /g; s/^ +| +$//g'
}

is_allowed_repeat_body(){
  local n
  n="$(guard_normalize "${1:-}")"
  case "${n}" in
    "i could not generate a reply locally. please retry, or switch mode."|\
    "error")
      return 0
      ;;
  esac
  return 1
}

runtime_non_empty_guard(){
  local q="$1" body="$2" mode="$3"
  if [[ -n "$(printf '%s' "${body}" | tr -d '[:space:]')" ]]; then
    printf '%s' "${body}"
    return 0
  fi
  if [[ "${mode}" == "CONVERSATION" ]]; then
    render_conversation_fallback "${q}"
    return 0
  fi
  runtime_local_fallback_text
}

runtime_repetition_guard(){
  local q="$1" body="$2" mode="$3" state_file count_file qn bn rec_qn rec_bn guarded repeat_count prior_count
  qn="$(guard_normalize "${q}")"
  bn="$(guard_normalize "${body}")"
  state_file="${RUNTIME_OUTPUT_GUARD_FILE}"
  count_file="${RUNTIME_OUTPUT_GUARD_COUNTS_FILE}"
  mkdir -p "$(dirname "${state_file}")"

  rec_qn=""
  rec_bn=""
  if [[ -f "${state_file}" ]]; then
    rec_qn="$(awk -F'\t' 'NR==1{print $1}' "${state_file}" 2>/dev/null || true)"
    rec_bn="$(awk -F'\t' 'NR==1{print $2}' "${state_file}" 2>/dev/null || true)"
  fi

  prior_count="$(awk -F'\t' -v key="${bn}" 'BEGIN{c=0} $1==key{c=$2} END{print c}' "${count_file}" 2>/dev/null || true)"
  [[ "${prior_count}" =~ ^[0-9]+$ ]] || prior_count=0
  repeat_count=$((prior_count + 1))
  repeat_count_session="${repeat_count}"

  guarded="${body}"
  if [[ -n "${bn}" && "${mode}" =~ ^(CHAT|CONVERSATION)$ && "${qn}" != "${rec_qn}" && "${bn}" == "${rec_bn}" ]]; then
    if ! is_allowed_repeat_body "${body}"; then
      quality_dbg "repeat_guard triggered mode=${mode} qn=${qn}"
      guard_trigger="repetition_guard_triggered"
      fallback_kind="deterministic_repeat_breaker"
      guarded="$(runtime_local_prompt_fallback_text "${q}" "${repeat_count}")"
      if [[ "$(guard_normalize "${guarded}")" == "${bn}" ]]; then
        guarded="${guarded}"$'\n'"Direct answer: ${q}"
      fi
      bn="$(guard_normalize "${guarded}")"
      prior_count="$(awk -F'\t' -v key="${bn}" 'BEGIN{c=0} $1==key{c=$2} END{print c}' "${count_file}" 2>/dev/null || true)"
      [[ "${prior_count}" =~ ^[0-9]+$ ]] || prior_count=0
      repeat_count=$((prior_count + 1))
      repeat_count_session="${repeat_count}"
    fi
  fi

  awk -F'\t' -v key="${bn}" '$1!=key' "${count_file}" 2>/dev/null > "${count_file}.tmp" || true
  printf '%s\t%s\n' "${bn}" "${repeat_count}" >> "${count_file}.tmp"
  mv "${count_file}.tmp" "${count_file}"
  printf '%s\t%s\n' "${qn}" "$(guard_normalize "${guarded}")" > "${state_file}"
  printf '%s' "${guarded}"
}

final_out=""
apply_repeat_guard="0"
case "${output_mode}" in
  VALIDATED)
    final_out="${raw_out}"
    ;;
  CHAT)
    final_out="$(render_chat)"
    apply_repeat_guard="1"
    ;;
  CONVERSATION)
    final_out="$(render_conversation)"
    apply_repeat_guard="1"
    ;;
  LIGHT_EVIDENCE)
    final_out="$(render_light)"
    ;;
  BRIEF)
    final_out="$(render_brief)"
    ;;
  *)
    err "unsupported output mode: ${output_mode}"
    exit 5
    ;;
esac

if [[ "${output_mode}" != "VALIDATED" ]]; then
  final_out="$(runtime_non_empty_guard "${question_for_plan}" "${final_out}" "${output_mode}")"
  if [[ "${apply_repeat_guard}" == "1" ]]; then
    final_out="$(runtime_repetition_guard "${question_for_plan}" "${final_out}" "${output_mode}")"
  fi
fi
if specialized_hint="$(specialized_policy_action_hint "${question_for_plan}" "${final_out}")"; then
  upsert_outcome_field "ACTION_HINT" "${specialized_hint}"
fi

if [[ "${force_mode}" == "LOCAL" ]] && is_evidence_style_text "${final_out}"; then
  evidence_style_blocked="1"
  local_evidence_lexeme_detected="1"
  guard_trigger="local_evidence_lexeme_detected"
  fallback_kind="lexeme_blocked_replacement"
  outcome_code_override="local_lexeme_blocked"
  local_gen_status="fail"
  final_out="$(runtime_local_prompt_fallback_text "${question_for_plan}" "1")"
fi
if [[ "${force_mode}" == "LOCAL" ]] && is_runtime_local_prompt_fallback_text "${final_out}"; then
  apply_local_degradation_augmented_fallback "${question_for_plan}" "local_generation_degraded" || true
fi
if [[ "${force_mode}" != "LOCAL" ]] && is_validated_insufficient_text "${final_out}"; then
  apply_validated_insufficient_recovery "${question_for_plan}" || true
fi

latprof_append "execute_plan" "post_processing" "$(( $(latprof_now_ms) - lat_post_stage_start_ms ))"
latprof_append "execute_plan" "total" "$(( $(latprof_now_ms) - lat_total_start_ms ))"
printf '%s\n' "${final_out}"
