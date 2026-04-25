#!/usr/bin/env bash
set -euo pipefail

# classify_query.sh
# Deterministic query classifier (envelope-level).
# Output: single JSON line to stdout; append same to audit log.

CLASSIFIER_VERSION="classifier_v1"

CONF_DIR="${LUCY_CONF_DIR:-$HOME/lucy/config}"
LOG_DIR="${LUCY_LOG_DIR:-$HOME/lucy/logs}"

ROLES_FILE="$CONF_DIR/roles_v1.txt"
TESTS_FILE="$CONF_DIR/classifier_tests_v1.tsv"
AUDIT_LOG="$LOG_DIR/classifier_audit.jsonl"

mkdir -p "$LOG_DIR"

usage() {
  cat <<'USAGE'
Usage:
  classify_query.sh "query text"
  classify_query.sh --selftest
Env:
  LUCY_CONF_DIR (default: $HOME/lucy/config)
  LUCY_LOG_DIR  (default: $HOME/lucy/logs)
USAGE
}

json_escape() {
  # Escape JSON special chars: backslash, double-quote, newline, tab, carriage return.
  # Input via stdin, output to stdout.
  sed -e 's/\\/\\\\/g' \
      -e 's/"/\\"/g' \
      -e ':a;N;$!ba;s/\n/\\n/g' \
      -e 's/\t/\\t/g' \
      -e 's/\r/\\r/g'
}

normalize_query() {
  # Deterministic normalization:
  # - trim
  # - collapse whitespace to single space
  # - lowercase ASCII
  local s
  s="$1"
  # trim leading/trailing whitespace
  s="$(printf "%s" "$s" | sed -e 's/^[[:space:]]\+//' -e 's/[[:space:]]\+$//')"
  # collapse internal whitespace
  s="$(printf "%s" "$s" | tr -s '[:space:]' ' ')"
  # lowercase (ASCII)
  s="$(printf "%s" "$s" | tr 'A-Z' 'a-z')"
  printf "%s" "$s"
}

contains_word() {
  # whole-word match (POSIX-ish). Use grep -E with word boundaries approximated.
  # $1 = haystack, $2 = word
  local h w
  h="$1"
  w="$2"
  printf "%s" "$h" | grep -Eqi "(^|[^a-z0-9])${w}([^a-z0-9]|$)"
}

contains_phrase() {
  # substring match, case already normalized
  # $1 = haystack, $2 = phrase
  case "$1" in
    *"$2"*) return 0 ;;
    *) return 1 ;;
  esac
}

has_prefix() {
  # prefix match after normalization
  # $1 = haystack, $2 = prefix
  case "$1" in
    "$2"*) return 0 ;;
    *) return 1 ;;
  esac
}

contains_regex() {
  # regex match (extended)
  # $1 = haystack, $2 = regex
  printf "%s" "$1" | grep -Eqi "$2"
}

load_roles() {
  if [ ! -f "$ROLES_FILE" ]; then
    echo "ERROR: missing roles file: $ROLES_FILE" >&2
    exit 2
  fi
}

signal_any_role() {
  # true if any role phrase appears as substring in normalized query.
  # Roles are already lowercase in roles_v1.txt (as per contract).
  local q line
  q="$1"
  while IFS= read -r line; do
    [ -z "$line" ] && continue
    if contains_phrase "$q" "$line"; then
      return 0
    fi
  done < "$ROLES_FILE"
  return 1
}

signal_any_time_cue() {
  local q
  q="$1"

  # TIME-CUE list (must match spec)
  contains_phrase "$q" "latest" && return 0
  contains_phrase "$q" "most recent" && return 0
  contains_phrase "$q" "today" && return 0
  contains_phrase "$q" "current" && return 0
  contains_phrase "$q" "currently" && return 0
  contains_phrase "$q" "now" && return 0
  contains_phrase "$q" "right now" && return 0
  contains_phrase "$q" "this week" && return 0
  contains_phrase "$q" "this month" && return 0
  contains_phrase "$q" "this year" && return 0
  contains_phrase "$q" "recent" && return 0
  contains_phrase "$q" "recently" && return 0
  contains_phrase "$q" "as of" && return 0
  contains_phrase "$q" "at the moment" && return 0
  contains_phrase "$q" "up to date" && return 0
  contains_phrase "$q" "update on" && return 0

  return 1
}

signal_relative_date() {
  local q
  q="$1"
  contains_word "$q" "yesterday" && return 0
  contains_word "$q" "tomorrow" && return 0
  contains_phrase "$q" "last night" && return 0
  contains_phrase "$q" "this morning" && return 0
  contains_phrase "$q" "tonight" && return 0
  contains_phrase "$q" "next week" && return 0
  return 1
}

signal_absolute_date() {
  local q
  q="$1"
  # YYYY-MM-DD
  contains_regex "$q" "\\b[0-9]{4}-[0-9]{2}-[0-9]{2}\\b" && return 0
  # D/M/YYYY or DD/MM/YYYY
  contains_regex "$q" "\\b[0-9]{1,2}/[0-9]{1,2}/[0-9]{4}\\b" && return 0
  # month name + day (english)
  contains_regex "$q" "\\b(jan|january|feb|february|mar|march|apr|april|may|jun|june|jul|july|aug|august|sep|sept|september|oct|october|nov|november|dec|december)[[:space:]]+[0-9]{1,2}\\b" && return 0
  contains_regex "$q" "\\b[0-9]{1,2}[[:space:]]+(jan|january|feb|february|mar|march|apr|april|may|jun|june|jul|july|aug|august|sep|sept|september|oct|october|nov|november|dec|december)\\b" && return 0
  return 1
}

signal_market_data() {
  local q
  q="$1"
  contains_phrase "$q" "price of" && return 0
  contains_phrase "$q" "exchange rate" && return 0
  contains_phrase "$q" "market cap" && return 0
  contains_phrase "$q" "bond yield" && return 0
  contains_phrase "$q" "interest rate" && return 0

  contains_word "$q" "stock" && return 0
  contains_word "$q" "shares" && return 0
  contains_word "$q" "usd" && return 0
  contains_word "$q" "eur" && return 0
  contains_word "$q" "ils" && return 0
  contains_word "$q" "bitcoin" && return 0
  contains_word "$q" "btc" && return 0
  contains_word "$q" "ethereum" && return 0
  contains_word "$q" "eth" && return 0
  contains_word "$q" "inflation" && return 0
  contains_word "$q" "cpi" && return 0

  return 1
}

signal_news_keyword() {
  local q
  q="$1"
  contains_word "$q" "news" && return 0
  contains_word "$q" "headlines" && return 0
  contains_word "$q" "breaking" && return 0
  contains_word "$q" "updates" && return 0
  contains_word "$q" "update" && return 0
  contains_phrase "$q" "latest news" && return 0
  return 1
}

rule_NEWS_KEYWORD() {
  local q
  q="$1"
  signal_news_keyword "$q"
}

rule_NEWS_GEO_POLITY() {
  local q
  q="$1"

  # requires: any_word among geo/polity AND any_time_cue true
  if ! signal_any_time_cue "$q"; then
    return 1
  fi

  contains_word "$q" "israel" && return 0
  contains_word "$q" "gaza" && return 0
  contains_word "$q" "hamas" && return 0
  contains_word "$q" "hezbollah" && return 0
  contains_word "$q" "iran" && return 0
  contains_word "$q" "idf" && return 0
  contains_word "$q" "knesset" && return 0
  contains_word "$q" "un" && return 0
  contains_word "$q" "eu" && return 0

  return 1
}

rule_NEWS_TODAY_IMPLIED() {
  local q
  q="$1"

  # match_any_prefix
  if ! ( has_prefix "$q" "what happened" || has_prefix "$q" "what's happening" || has_prefix "$q" "what is happening" ); then
    return 1
  fi

  # requires any_phrase time words
  contains_phrase "$q" "today" && return 0
  contains_phrase "$q" "now" && return 0
  contains_phrase "$q" "right now" && return 0
  contains_phrase "$q" "this morning" && return 0
  contains_phrase "$q" "tonight" && return 0

  return 1
}

rule_TIME_CUE() {
  local q
  q="$1"
  signal_any_time_cue "$q"
}

rule_DATE_RELATIVE() {
  local q
  q="$1"
  signal_relative_date "$q"
}

rule_DATE_ABSOLUTE_ISO() {
  local q
  q="$1"
  contains_regex "$q" "\\b[0-9]{4}-[0-9]{2}-[0-9]{2}\\b"
}

rule_DATE_ABSOLUTE_SLASH() {
  local q
  q="$1"
  contains_regex "$q" "\\b[0-9]{1,2}/[0-9]{1,2}/[0-9]{4}\\b"
}

rule_DATE_ABSOLUTE_MONTHNAME() {
  local q
  q="$1"
  contains_regex "$q" "\\b(jan|january|feb|february|mar|march|apr|april|may|jun|june|jul|july|aug|august|sep|sept|september|oct|october|nov|november|dec|december)[[:space:]]+[0-9]{1,2}\\b" && return 0
  contains_regex "$q" "\\b[0-9]{1,2}[[:space:]]+(jan|january|feb|february|mar|march|apr|april|may|jun|june|jul|july|aug|august|sep|sept|september|oct|october|nov|november|dec|december)\\b"
}

rule_OFFICE_HOLDER() {
  local q
  q="$1"

  # requires any_phrase: who is (etc)
  if ! ( contains_phrase "$q" "who is the" || contains_phrase "$q" "who's the" || contains_phrase "$q" "who is" || contains_phrase "$q" "who's" ); then
    return 1
  fi

  # requires2 any_role
  if ! signal_any_role "$q"; then
    return 1
  fi

  return 0
}

rule_MARKET_DATA() {
  local q
  q="$1"
  signal_market_data "$q"
}

rule_REGULATION() {
  local q
  q="$1"

  # requires any_word in set
  if ! ( contains_word "$q" "law" || contains_word "$q" "legal" || contains_word "$q" "regulation" || contains_word "$q" "rules" || contains_word "$q" "policy" || contains_word "$q" "guidelines" ); then
    return 1
  fi

  # requires2 any_word in set (keep as words; "as of" already covered by TIME-CUE)
  contains_word "$q" "new" && return 0
  contains_word "$q" "changed" && return 0
  contains_word "$q" "updated" && return 0
  contains_word "$q" "current" && return 0
  contains_word "$q" "latest" && return 0
  contains_word "$q" "as" && return 0

  return 1
}

classify() {
  local raw norm ts mode decisive all_rules
  local time_cue_present relative_date_present absolute_date_present office_holder_present market_data_present news_keyword_present

  raw="$1"
  norm="$(normalize_query "$raw")"
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

  load_roles

  time_cue_present=false
  relative_date_present=false
  absolute_date_present=false
  office_holder_present=false
  market_data_present=false
  news_keyword_present=false

  signal_any_time_cue "$norm" && time_cue_present=true
  signal_relative_date "$norm" && relative_date_present=true
  signal_absolute_date "$norm" && absolute_date_present=true
  rule_OFFICE_HOLDER "$norm" && office_holder_present=true
  signal_market_data "$norm" && market_data_present=true
  signal_news_keyword "$norm" && news_keyword_present=true

  mode="LOCAL"
  decisive="-"
  all_rules=""

  # Ordered evaluation (must match spec precedence and rule order)
  if rule_NEWS_KEYWORD "$norm"; then
    mode="NEWS"
    decisive="NEWS-KEYWORD"
    all_rules="NEWS-KEYWORD"
  fi

  if rule_NEWS_GEO_POLITY "$norm"; then
    if [ "$decisive" = "-" ]; then
      mode="NEWS"
      decisive="NEWS-GEO-POLITY"
      all_rules="NEWS-GEO-POLITY"
    else
      all_rules="$all_rules,NEWS-GEO-POLITY"
    fi
  fi

  if rule_NEWS_TODAY_IMPLIED "$norm"; then
    if [ "$decisive" = "-" ]; then
      mode="NEWS"
      decisive="NEWS-TODAY-IMPLIED"
      all_rules="NEWS-TODAY-IMPLIED"
    else
      all_rules="$all_rules,NEWS-TODAY-IMPLIED"
    fi
  fi

  if rule_TIME_CUE "$norm"; then
    if [ "$decisive" = "-" ]; then
      mode="EVIDENCE"
      decisive="TIME-CUE"
      all_rules="TIME-CUE"
    else
      all_rules="$all_rules,TIME-CUE"
    fi
  fi

  if rule_DATE_RELATIVE "$norm"; then
    if [ "$decisive" = "-" ]; then
      mode="EVIDENCE"
      decisive="DATE-RELATIVE"
      all_rules="DATE-RELATIVE"
    else
      all_rules="$all_rules,DATE-RELATIVE"
    fi
  fi

  if rule_DATE_ABSOLUTE_ISO "$norm"; then
    if [ "$decisive" = "-" ]; then
      mode="EVIDENCE"
      decisive="DATE-ABSOLUTE-ISO"
      all_rules="DATE-ABSOLUTE-ISO"
    else
      all_rules="$all_rules,DATE-ABSOLUTE-ISO"
    fi
  fi

  if rule_DATE_ABSOLUTE_SLASH "$norm"; then
    if [ "$decisive" = "-" ]; then
      mode="EVIDENCE"
      decisive="DATE-ABSOLUTE-SLASH"
      all_rules="DATE-ABSOLUTE-SLASH"
    else
      all_rules="$all_rules,DATE-ABSOLUTE-SLASH"
    fi
  fi

  if rule_DATE_ABSOLUTE_MONTHNAME "$norm"; then
    if [ "$decisive" = "-" ]; then
      mode="EVIDENCE"
      decisive="DATE-ABSOLUTE-MONTHNAME"
      all_rules="DATE-ABSOLUTE-MONTHNAME"
    else
      all_rules="$all_rules,DATE-ABSOLUTE-MONTHNAME"
    fi
  fi

  if rule_OFFICE_HOLDER "$norm"; then
    if [ "$decisive" = "-" ]; then
      mode="EVIDENCE"
      decisive="OFFICE-HOLDER"
      all_rules="OFFICE-HOLDER"
    else
      all_rules="$all_rules,OFFICE-HOLDER"
    fi
  fi

  if rule_MARKET_DATA "$norm"; then
    if [ "$decisive" = "-" ]; then
      mode="EVIDENCE"
      decisive="MARKET-DATA"
      all_rules="MARKET-DATA"
    else
      all_rules="$all_rules,MARKET-DATA"
    fi
  fi

  if rule_REGULATION "$norm"; then
    if [ "$decisive" = "-" ]; then
      mode="EVIDENCE"
      decisive="REGULATION"
      all_rules="REGULATION"
    else
      all_rules="$all_rules,REGULATION"
    fi
  fi

  # Build JSON arrays from all_rules CSV
  local all_rules_json
  if [ -z "$all_rules" ]; then
    all_rules_json="[]"
  else
    all_rules_json="[\"$(printf "%s" "$all_rules" | sed 's/,/","/g')\"]"
  fi

  local raw_esc norm_esc
  raw_esc="$(printf "%s" "$raw" | json_escape)"
  norm_esc="$(printf "%s" "$norm" | json_escape)"

  local line
  line="{\"ts_utc\":\"$ts\",\"query_raw\":\"$raw_esc\",\"query_norm\":\"$norm_esc\",\"mode\":\"$mode\",\"decisive_rule\":\"$decisive\",\"all_rules\":$all_rules_json,\"signals\":{\"time_cue_present\":$time_cue_present,\"relative_date_present\":$relative_date_present,\"absolute_date_present\":$absolute_date_present,\"office_holder_present\":$office_holder_present,\"market_data_present\":$market_data_present,\"news_keyword_present\":$news_keyword_present},\"classifier_version\":\"$CLASSIFIER_VERSION\"}"

  printf "%s\n" "$line" | tee -a "$AUDIT_LOG" >/dev/null
  printf "%s\n" "$line"
}

selftest() {
  if [ ! -f "$TESTS_FILE" ]; then
    echo "ERROR: missing tests file: $TESTS_FILE" >&2
    exit 2
  fi

  local fail=0
  local q exp_mode exp_rule got_mode got_rule

  while IFS= read -r line; do
    [ -z "$line" ] && continue
    case "$line" in
      \#*) continue ;;
    esac

    q="$(printf "%s" "$line" | awk -F'\t' '{print $1}')"
    exp_mode="$(printf "%s" "$line" | awk -F'\t' '{print $2}')"
    exp_rule="$(printf "%s" "$line" | awk -F'\t' '{print $3}')"

    out="$(classify "$q")"
    got_mode="$(printf "%s" "$out" | sed -n 's/.*"mode":"\([^"]*\)".*/\1/p')"
    got_rule="$(printf "%s" "$out" | sed -n 's/.*"decisive_rule":"\([^"]*\)".*/\1/p')"

    if [ "$exp_mode" != "$got_mode" ]; then
      echo "FAIL: mode: [$q] expected=$exp_mode got=$got_mode" >&2
      fail=1
      continue
    fi

    if [ "$exp_rule" != "-" ] && [ "$exp_rule" != "$got_rule" ]; then
      echo "FAIL: rule: [$q] expected=$exp_rule got=$got_rule" >&2
      fail=1
      continue
    fi

    echo "OK: [$q] -> $got_mode / $got_rule"
  done < "$TESTS_FILE"

  return "$fail"
}

main() {
  if [ $# -lt 1 ]; then
    usage
    exit 2
  fi

  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    --selftest)
      selftest
      ;;
    *)
      classify "$*"
      ;;
  esac
}

main "$@"
