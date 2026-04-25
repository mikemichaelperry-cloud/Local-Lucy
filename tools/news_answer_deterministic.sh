#!/usr/bin/env bash
set -euo pipefail

main() {
  if [ $# -lt 1 ] || [ $# -gt 2 ]; then
    echo "ERROR: expected digest path [query]" >&2
    exit 2
  fi

  digest="$1"
  query="${2:-}"
  if [ ! -f "$digest" ]; then
    echo "ERROR: missing digest: $digest" >&2
    exit 2
  fi

  python3 - "$digest" "$query" <<'PY'
import email.utils
import re
import sys
import os
from datetime import datetime, timedelta, timezone

digest_path = sys.argv[1]
query = sys.argv[2] if len(sys.argv) > 2 else ""
ql = query.lower()
try:
    NEWS_MAX_ITEMS = int(os.environ.get("LUCY_NEWS_MAX_ITEMS", "10"))
except Exception:
    NEWS_MAX_ITEMS = 10
if NEWS_MAX_ITEMS < 1:
    NEWS_MAX_ITEMS = 1
try:
    NEWS_MAX_PER_DOMAIN = int(os.environ.get("LUCY_NEWS_MAX_PER_DOMAIN", "2"))
except Exception:
    NEWS_MAX_PER_DOMAIN = 2
if NEWS_MAX_PER_DOMAIN < 1:
    NEWS_MAX_PER_DOMAIN = 1

KW_ISRAEL_1 = re.compile(r"(israel|gaza|west bank|jerusalem|idf|knesset)", re.I)
KW_ISRAEL_2 = re.compile(r"(netanyahu|hamas|hezbollah|tel aviv)", re.I)
ISRAEL_FOCUS_DOMS = {
    "timesofisrael.com", "jpost.com", "haaretz.com", "ynet.co.il", "ynetnews.com",
    "idf.il", "www.idf.il", "gov.il", "www.gov.il"
}
AU_DOMS = ("abc.net.au", "sbs.com.au", "smh.com.au")
AU_INTENT_RE = re.compile(r"(^|[^a-z0-9_])(australia|australian|canberra|sydney|melbourne|brisbane|perth|adelaide)([^a-z0-9_]|$)", re.I)
ISRAEL_INTENT_RE = re.compile(r"(^|[^a-z0-9_])(israel|israeli|gaza|idf|west bank|jerusalem|tel aviv)([^a-z0-9_]|$)", re.I)
LATEST_INTENT_RE = re.compile(r"(^|[^a-z0-9_])(latest|newest|current|today|now)([^a-z0-9_]|$)", re.I)
PREDICT_INTENT_RE = re.compile(
    r"(^|[^a-z0-9_])(predict|prediction|forecast|outcome|who\s+will\s+win|how\s+will\s+.*\s+end|endgame)([^a-z0-9_]|$)",
    re.I,
)
CONFLICT_CONTEXT_RE = re.compile(
    r"(^|[^a-z0-9_])(war|conflict|military\s+action|military\s+operation|hostilities|ceasefire|airstrike|air\s+strike|missile|invasion)([^a-z0-9_]|$)",
    re.I,
)
TERMINAL_PUNCTUATION_RE = re.compile(r'[.!?]["\')\]”’]*$')


def parse_dt(value: str):
    s = (value or "").strip()
    if not s:
        return None
    try:
        dt = email.utils.parsedate_to_datetime(s)
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S%z"):
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            continue
    return None


def parse_digest(path: str):
    ts = ""
    entries = []
    in_body = False
    cur = {}
    idx = 0

    def flush():
      nonlocal cur, idx
      if not cur:
          return
      dom = (cur.get("domain") or "").strip()
      title = (cur.get("title") or "").strip()
      if dom and title and title != "----":
          item = {
              "idx": idx,
              "domain": dom,
              "date": (cur.get("date") or "").strip(),
              "title": title,
              "desc": (cur.get("desc") or "").strip(),
          }
          item["dt"] = parse_dt(item["date"])
          entries.append(item)
          idx += 1
      cur = {}

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.rstrip("\n")
            if not in_body:
                if line.startswith("DIGEST_UTC=") and not ts:
                    ts = line.split("=", 1)[1].strip()
                if line == "====":
                    in_body = True
                continue

            t = line.strip()
            if not t:
                continue
            if t == "----":
                flush()
                continue
            if t.startswith("DOMAIN: "):
                cur["domain"] = t[len("DOMAIN: "):]
            elif t.startswith("DATE: "):
                cur["date"] = t[len("DATE: "):]
            elif t.startswith("TITLE: "):
                cur["title"] = t[len("TITLE: "):]
            elif t.startswith("DESC: "):
                cur["desc"] = t[len("DESC: "):]
    flush()
    return ts, entries


def item_text(item):
    return (item.get("title", "") + " " + item.get("desc", "")).lower()


def is_israel_relevant(item):
    dom = (item.get("domain") or "").lower()
    txt = item_text(item)
    return bool(KW_ISRAEL_1.search(txt) or KW_ISRAEL_2.search(txt) or dom in ISRAEL_FOCUS_DOMS)


def sort_entries(entries):
    return sorted(
        entries,
        key=lambda e: (
            0 if e["dt"] is not None else 1,
            -(e["dt"].timestamp()) if e["dt"] is not None else 0,
            e["idx"],
        ),
    )


def recency_filter(entries, digest_ts):
    au_intent = bool(AU_INTENT_RE.search(ql))
    au_entries = [e for e in entries if e.get("domain", "").lower() in AU_DOMS]
    if not LATEST_INTENT_RE.search(ql):
        return entries
    ref = parse_dt(digest_ts) or datetime.now(timezone.utc)
    dated = [e for e in entries if e["dt"] is not None]
    undated = [e for e in entries if e["dt"] is None]
    if not dated:
        return entries
    for days, min_keep in ((7, 3), (30, 3), (120, 2)):
        cutoff = ref - timedelta(days=days)
        kept = [e for e in dated if e["dt"] >= cutoff]
        if len(kept) >= min_keep:
            out = sort_entries(kept + undated)
            if au_intent and au_entries:
                # Preserve AU-source visibility for AU intent, even if AU entries are older.
                seen = {e["idx"] for e in out}
                for e in sort_entries(au_entries):
                    if e["idx"] in seen:
                        continue
                    out.append(e)
                    seen.add(e["idx"])
                    if sum(1 for x in out if x.get("domain", "").lower() in AU_DOMS) >= 3:
                        break
                out = sort_entries(out)
            return out
    # Fallback: at least remove obviously stale year-old items when fresher data exists.
    cutoff = ref - timedelta(days=180)
    kept = [e for e in dated if e["dt"] >= cutoff]
    out = sort_entries((kept or dated) + undated)
    if au_intent and au_entries:
        seen = {e["idx"] for e in out}
        for e in sort_entries(au_entries):
            if e["idx"] in seen:
                continue
            out.append(e)
            seen.add(e["idx"])
            if sum(1 for x in out if x.get("domain", "").lower() in AU_DOMS) >= 3:
                break
        out = sort_entries(out)
    return out


def select_items(entries):
    max_items = NEWS_MAX_ITEMS
    picked = []
    picked_idx = set()
    dom_picked = set()
    dom_counts = {}
    au_intent = bool(AU_INTENT_RE.search(ql))
    israel_intent = bool(ISRAEL_INTENT_RE.search(ql))

    def pick(item, mark_domain=False, enforce_domain_cap=False):
        dom = item["domain"]
        if item["idx"] in picked_idx or len(picked) >= max_items:
            return
        if enforce_domain_cap and dom_counts.get(dom, 0) >= NEWS_MAX_PER_DOMAIN:
            return
        picked.append(item)
        picked_idx.add(item["idx"])
        dom_counts[dom] = dom_counts.get(dom, 0) + 1
        if mark_domain:
            dom_picked.add(dom)

    if au_intent:
        # AU-intent: front-load AU publishers first.
        for item in entries:
            if item["domain"].lower() in AU_DOMS and item["domain"] not in dom_picked:
                pick(item, mark_domain=True)
        for item in entries:
            if item["domain"].lower() in AU_DOMS:
                pick(item, enforce_domain_cap=True)
        if picked:
            # Keep AU-only when available; avoid drowning AU intent in generic world fills.
            return picked[:max_items]

    if israel_intent:
        for item in entries:
            if KW_ISRAEL_1.search(item_text(item)) and item["domain"] not in dom_picked:
                pick(item, mark_domain=True)
        for item in entries:
            if KW_ISRAEL_2.search(item_text(item)) and item["domain"] not in dom_picked:
                pick(item, mark_domain=True)
        for item in entries:
            if item["domain"].lower() in ISRAEL_FOCUS_DOMS and item["domain"] not in dom_picked:
                pick(item, mark_domain=True)

    if israel_intent:
        # For Israel-specific queries, avoid leaking unrelated world headlines.
        for item in entries:
            if is_israel_relevant(item):
                pick(item)
        return picked[:max_items]

    # Generic diversity pass: newest one per domain.
    for item in entries:
        if item["domain"] not in dom_picked:
            pick(item, mark_domain=True)

    # Intent-specific follow-up passes.
    if israel_intent:
        for item in entries:
            if KW_ISRAEL_1.search(item_text(item)):
                pick(item)
        for item in entries:
            if KW_ISRAEL_2.search(item_text(item)):
                pick(item)

    # Fill by recency.
    for item in entries:
        pick(item, enforce_domain_cap=True)

    return picked[:max_items]


def should_emit_bounded_forecast(query_lower: str) -> bool:
    if not query_lower:
        return False
    return bool(PREDICT_INTENT_RE.search(query_lower) and CONFLICT_CONTEXT_RE.search(query_lower))


def ensure_terminal_punctuation(text: str) -> str:
    cleaned = (text or "").strip()
    if not cleaned:
        return cleaned
    if TERMINAL_PUNCTUATION_RE.search(cleaned):
        return cleaned
    return cleaned + "."


def main():
    ts, entries = parse_digest(digest_path)
    print("BEGIN_VALIDATED")
    print(f"Summary: Latest items extracted from allowlisted sources as of {ts}.")
    print("Key items:")
    if not entries:
        print("Insufficient evidence from trusted sources.")
        print("END_VALIDATED")
        return

    ordered = sort_entries(entries)
    filtered = recency_filter(ordered, ts)
    selected = select_items(filtered)

    for item in selected:
        title = ensure_terminal_punctuation(item["title"])
        if item.get("date"):
            print(f"- [{item['domain']}] ({item['date']}): {title}")
        else:
            print(f"- [{item['domain']}] : {title}")

    if should_emit_bounded_forecast(ql):
        print("Bounded forecast (not a deterministic prediction):")
        print("- Base case (24-72h): continued retaliatory exchanges and elevated alert posture.")
        print("- Alternative: limited de-escalation if credible third-party mediation gains traction.")
        print("- Tail risk: broader regional spillover involving additional actors or theaters.")
        print("Forecast confidence: low (headline-only extract; no cross-article reconciliation).")

    print("Conflicts/uncertainty: None assessed (deterministic extract only; no cross-article reconciliation).")
    seen = set()
    source_domains = []
    for item in selected:
        d = item["domain"]
        if d in seen:
            continue
        seen.add(d)
        source_domains.append(d)
    if source_domains:
        print("Sources:")
        for d in source_domains:
            print(f"- {d}")
    print("END_VALIDATED")


if __name__ == "__main__":
    main()
PY
}

main "$@"
