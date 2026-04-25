#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  build_news_digest.sh EVIDENCE_PACK OUT_DIGEST
Extracts a deterministic digest from the evidence pack.
Supports multiple TITLE/DATE/DESC blocks inside a single evidence item (RSS).
USAGE
}

main() {
  if [ $# -ne 2 ]; then
    usage
    exit 2
  fi

  pack="$1"
  out="$2"

  if [ ! -f "$pack" ]; then
    echo "ERROR: missing pack: $pack" >&2
    exit 2
  fi

  : > "$out"

  awk '
    BEGIN {
      inblk=0
      dom=""
      title=""
      date=""
      desc=""
    }

    function trim(s) {
      gsub(/^[ \t\r]+/, "", s)
      gsub(/[ \t\r]+$/, "", s)
      return s
    }

    function emit_one() {
      # Repair: TITLE ---- with DESC: TITLE: X
      if (title == "----" && desc ~ /^TITLE: /) {
        sub(/^TITLE: /, "", desc)
        title = desc
        desc = ""
      }

      if (dom == "" || title == "" || title == "----") return
      if (title ~ /RSS for Node/) return

      seen[dom]++
      if (seen[dom] > 6) return

      print "DOMAIN: " dom
      if (date != "") print "DATE: " date
      print "TITLE: " title
      if (desc != "") print "DESC: " desc
      print "----"
    }

    function reset_entry() {
      title=""
      date=""
      desc=""
    }

    /^BEGIN_EVIDENCE_ITEM/ {
      inblk=1
      dom=""
      reset_entry()
      next
    }

    /^END_EVIDENCE_ITEM/ {
      # Emit any pending entry at end of evidence item
      emit_one()
      inblk=0
      next
    }

    inblk==1 {
      line = trim($0)

      # Domain marker injected by pack builder
      if (line ~ /^DOMAIN=/) { sub(/^DOMAIN=/, "", line); dom=line; next }

      # RSS extractor output: repeated TITLE/DATE/DESC blocks
      if (line ~ /^TITLE:[[:space:]]*/) {
        sub(/^TITLE:[[:space:]]*/, "", line)

        # If we already have a title, this starts a NEW entry -> emit the previous one first.
        if (title != "") {
          emit_one()
          reset_entry()
        }

        title=line
        next
      }

      if (line ~ /^DATE:[[:space:]]*/) {
        sub(/^DATE:[[:space:]]*/, "", line)
        if (date == "") date=line
        next
      }

      if (line ~ /^DESC:[[:space:]]*/) {
        sub(/^DESC:[[:space:]]*/, "", line)
        if (desc == "") desc=line
        next
      }

      # Fallback: ignore other lines
      next
    }
  ' "$pack" \
  | awk '
    /^DESC: / {
      s=$0
      sub(/^DESC: /,"",s)
      if (length(s) > 600) s=substr(s,1,600) "..."
      print "DESC: " s
      next
    }
    { print }
  ' >> "$out"

  doms="$(grep -E '^DOMAIN: ' "$out" | sed 's/^DOMAIN: //' | sort -u | tr '\n' ' ' | tr -s ' ' ' ' | sed -e 's/[[:space:]]\+$//')"

  tmp="$out.tmp"
  {
    echo "DIGEST_UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "SOURCES=$doms"
    echo "===="
    cat "$out"
  } > "$tmp"
  mv "$tmp" "$out"

  echo "OK: digest built: $out"
}

main "$@"
