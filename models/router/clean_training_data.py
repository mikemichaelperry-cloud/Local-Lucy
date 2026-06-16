#!/usr/bin/env python3
"""
Clean and rebalance the router training data (comprehensive_examples.json).

Usage:
    python clean_training_data.py

Produces:
    - comprehensive_examples_clean.json  (cleaned dataset)
    - comprehensive_examples_flagged.json  (entries needing manual review)
    - clean_report.txt  (statistics and recommendations)
"""

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parent.resolve()
INPUT_PATH = ROOT / "comprehensive_examples.json"
CLEAN_PATH = ROOT / "comprehensive_examples_clean.json"
FLAGGED_PATH = ROOT / "comprehensive_examples_flagged.json"
REPORT_PATH = ROOT / "clean_report.txt"

# ---------------------------------------------------------------------------
# Garbage detection
# ---------------------------------------------------------------------------

_INJECTION_PATTERNS = [
    re.compile(r"<script", re.IGNORECASE),
    re.compile(r"javascript:", re.IGNORECASE),
    re.compile(r"on\w+\s*=", re.IGNORECASE),  # onclick=, onerror=, etc.
    re.compile(r"[<>{}]\s*\w+\s*[=;]"),  # basic HTML/code injection
]


def _is_garbage(query: str) -> tuple[bool, str]:
    """Return (is_garbage, reason)."""
    q = query.strip()
    if not q:
        return True, "empty"

    # Too short (conversation fillers: "yes", "ok", "huh?", "fine")
    if len(q) < 10:
        return True, f"too_short({len(q)}_chars)"

    # Single word repeated many times (e.g. "word word word ...")
    words = q.lower().split()
    if len(words) > 5 and len(set(words)) == 1:
        return True, "repeated_single_word"

    # Injection / XSS patterns
    for pat in _INJECTION_PATTERNS:
        if pat.search(q):
            return True, f"injection_pattern({pat.pattern[:20]})"

    # Excessive repetition of non-semantic content
    if q.lower().count("word ") > 5:
        return True, "nonsense_repetition"

    return False, ""


# ---------------------------------------------------------------------------
# Suspicious label detection
# ---------------------------------------------------------------------------

_ROUTE_KEYWORDS: dict[str, list[str]] = {
    "WEATHER": [
        "weather",
        "forecast",
        "rain",
        "snow",
        "sunny",
        "cloudy",
        "storm",
        "temperature",
        "temp",
        "hot",
        "cold",
        "warm",
        "cool",
        "humid",
        "drizzle",
        "thunder",
        "lightning",
        "fog",
        "wind",
        "breeze",
        "wetter",
        "wetterbericht",
        "pronostico",
        "tiempo",
        "météo",
    ],
    "NEWS": [
        "news",
        "latest",
        "breaking",
        "headline",
        "current events",
        "what happened",
        "update on",
        "report on",
        "developments",
    ],
    "TIME": [
        "time",
        "timezone",
        "hour",
        "clock",
        "what time",
        "when is",
        "schedule",
        "opening hours",
        "closing time",
        "business hours",
    ],
    "EVIDENCE": [
        "symptoms",
        "treatment",
        "diagnosis",
        "disease",
        "cancer",
        "diabetes",
        "appendicitis",
        "medical",
        "clinical",
        "study",
        "evidence",
        "research",
        "trial",
        "peer reviewed",
        "citation",
        "legal",
        "law",
        "statute",
        "regulation",
        "court",
        "financial",
        "stock",
        "bond",
        "investment",
        "sec filing",
    ],
    "AUGMENTED": [
        "what is",
        "how does",
        "explain",
        "why is",
        "compare",
        "difference between",
        "pros and cons",
        "history of",
    ],
}

# Keywords that strongly suggest a route, used to catch mislabels
_STRONG_ROUTE_INDICATORS: dict[str, list[str]] = {
    "WEATHER": [
        "weather forecast",
        "weather tomorrow",
        "weather today",
        "what's the weather",
        "how's the weather",
    ],
    "NEWS": ["latest news", "breaking news", "news about", "what's happening"],
    "TIME": ["what time is it", "what timezone", "time in ", "current time"],
    "EVIDENCE": ["symptoms of", "treatment for", "evidence for", "peer reviewed", "clinical trial"],
}

# Things that should NEVER be AUGMENTED/EVIDENCE/NEWS
_LOCAL_ONLY_PATTERNS = [
    re.compile(
        r"\b(write|compose|craft|tell me|create|make up)\b.*\b(story|poem|essay|fiction|tale|narrative)\b",
        re.IGNORECASE,
    ),
    re.compile(r"^\s*(calculate|compute|what is)\s*[\d+\-*/\s]+\?*$", re.IGNORECASE),
    re.compile(r"\bhello\b|\bhi\b|\bgood morning\b|\bgood evening\b", re.IGNORECASE),
]


def _is_suspicious_label(query: str, route: str) -> tuple[bool, str]:
    """Return (is_suspicious, reason)."""
    q = query.lower()

    # Creative writing should be LOCAL, never AUGMENTED/EVIDENCE/NEWS
    if route in ("AUGMENTED", "EVIDENCE", "NEWS"):
        for pat in _LOCAL_ONLY_PATTERNS:
            if pat.search(q):
                return True, f"creative_or_math_in_{route}"

    # Check strong route indicators against wrong labels
    for true_route, indicators in _STRONG_ROUTE_INDICATORS.items():
        if route != true_route:
            for ind in indicators:
                if ind in q:
                    return True, f"looks_like_{true_route}_but_labeled_{route}"

    # Check keyword coverage for each route
    expected_keywords = _ROUTE_KEYWORDS.get(route, [])
    if expected_keywords:
        has_keyword = any(kw in q for kw in expected_keywords)
        if not has_keyword:
            # Some routes don't need keywords (LOCAL is a catch-all)
            if route != "LOCAL":
                return True, f"no_{route}_keywords"

    # Medical/legal/financial keywords in LOCAL route = suspicious
    if route == "LOCAL":
        medical_finance_legal = [
            "symptoms",
            "treatment",
            "diagnosis",
            "cancer",
            "diabetes",
            "appendicitis",
            "legal",
            "lawyer",
            "stock price",
            "investment",
        ]
        if any(kw in q for kw in medical_finance_legal):
            return True, "medical_legal_finance_in_LOCAL"

    return False, ""


# ---------------------------------------------------------------------------
# Rebalancing
# ---------------------------------------------------------------------------

_TARGET_COUNTS = {
    "LOCAL": 300,
    "AUGMENTED": 150,
    "NEWS": 60,
    "TIME": 60,
    "WEATHER": 50,
    "EVIDENCE": 50,
    "EPHEMERAL": 30,
}


def _rebalance(clean_examples: list[dict], flagged_examples: list[dict]) -> list[dict]:
    """Remove excess examples from overrepresented routes."""
    route_groups: dict[str, list[dict]] = {r: [] for r in _TARGET_COUNTS}
    for ex in clean_examples:
        route = ex["labels"]["route"]
        route_groups.setdefault(route, []).append(ex)

    result = []
    for route, target in _TARGET_COUNTS.items():
        group = route_groups.get(route, [])
        if len(group) > target:
            # Keep the longest/most diverse examples (heuristic: prefer longer, more unique)
            group.sort(key=lambda ex: len(ex["query"]), reverse=True)
            kept = group[:target]
            dropped = group[target:]
            result.extend(kept)
            # Move dropped to flagged for review
            for ex in dropped:
                ex["_flag_reason"] = f"dropped_during_rebalance({route}: {len(group)}->{target})"
            flagged_examples.extend(dropped)
        else:
            result.extend(group)

    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    print(f"Loading {INPUT_PATH} ...")
    with open(INPUT_PATH) as f:
        examples: list[dict[str, Any]] = json.load(f)
    print(f"Loaded {len(examples)} examples.")

    clean: list[dict] = []
    flagged: list[dict] = []
    removed_stats = Counter()
    suspicion_stats = Counter()

    for ex in examples:
        query = ex.get("query", "")
        route = ex.get("labels", {}).get("route", "UNKNOWN")

        # 1. Garbage check
        is_garbage, garbage_reason = _is_garbage(query)
        if is_garbage:
            ex_copy = dict(ex)
            ex_copy["_flag_reason"] = f"GARBAGE:{garbage_reason}"
            flagged.append(ex_copy)
            removed_stats[f"garbage:{garbage_reason}"] += 1
            continue

        # 2. Suspicious label check
        is_suspicious, suspicion_reason = _is_suspicious_label(query, route)
        if is_suspicious:
            ex_copy = dict(ex)
            ex_copy["_flag_reason"] = f"SUSPICIOUS:{suspicion_reason}"
            flagged.append(ex_copy)
            suspicion_stats[f"{route}:{suspicion_reason}"] += 1
            # Still keep it in clean for now — user can review flagged later
            clean.append(ex)
        else:
            clean.append(ex)

    # 3. Rebalance
    before_rebalance = len(clean)
    clean = _rebalance(clean, flagged)
    after_rebalance = len(clean)

    # 4. Deduplicate (exact query match, keep first)
    seen_queries = set()
    deduped = []
    duplicates = 0
    for ex in clean:
        q_norm = ex["query"].strip().lower()
        if q_norm in seen_queries:
            duplicates += 1
            ex_copy = dict(ex)
            ex_copy["_flag_reason"] = "duplicate"
            flagged.append(ex_copy)
        else:
            seen_queries.add(q_norm)
            deduped.append(ex)
    clean = deduped

    # 5. Write outputs
    with open(CLEAN_PATH, "w") as f:
        json.dump(clean, f, indent=2, ensure_ascii=False)

    with open(FLAGGED_PATH, "w") as f:
        json.dump(flagged, f, indent=2, ensure_ascii=False)

    # 6. Build report
    old_routes = Counter(ex["labels"]["route"] for ex in examples)
    new_routes = Counter(ex["labels"]["route"] for ex in clean)

    report_lines = [
        "=" * 70,
        "ROUTER TRAINING DATA CLEANING REPORT",
        "=" * 70,
        "",
        f"Input file:   {INPUT_PATH}",
        f"Output clean: {CLEAN_PATH}",
        f"Output flagged: {FLAGGED_PATH}",
        "",
        "--- BEFORE vs AFTER ---",
        f"Total examples (input):     {len(examples)}",
        f"Total examples (clean):     {len(clean)}",
        f"Flagged for review:         {len(flagged)}",
        f"  - Garbage removed:        {sum(removed_stats.values())}",
        f"  - Suspicious labels:      {sum(suspicion_stats.values())}",
        f"  - Rebalance dropped:      {before_rebalance - after_rebalance}",
        f"  - Duplicates removed:     {duplicates}",
        "",
        "--- ROUTE DISTRIBUTION ---",
        f"{'Route':<15} {'Before':>8} {'After':>8} {'Target':>8} {'Status':<15}",
        "-" * 60,
    ]

    for route in sorted(_TARGET_COUNTS.keys(), key=lambda r: old_routes.get(r, 0), reverse=True):
        before = old_routes.get(route, 0)
        after = new_routes.get(route, 0)
        target = _TARGET_COUNTS.get(route, "N/A")
        if before == 0 and after == 0:
            continue
        if isinstance(target, int):
            if after < target * 0.5:
                status = "CRITICALLY LOW"
            elif after < target:
                status = "UNDER"
            elif after > target * 1.5:
                status = "OVER"
            else:
                status = "OK"
        else:
            status = "N/A"
        report_lines.append(f"{route:<15} {before:>8} {after:>8} {str(target):>8} {status:<15}")

    report_lines.extend(
        [
            "",
            "--- GARBAGE REMOVED ---",
        ]
    )
    for reason, count in sorted(removed_stats.items(), key=lambda x: -x[1]):
        report_lines.append(f"  {count:4d}  {reason}")

    report_lines.extend(
        [
            "",
            "--- SUSPICIOUS LABELS ---",
        ]
    )
    for reason, count in sorted(suspicion_stats.items(), key=lambda x: -x[1]):
        report_lines.append(f"  {count:4d}  {reason}")

    report_lines.extend(
        [
            "",
            "--- RECOMMENDATIONS ---",
            "1. Review flagged entries in comprehensive_examples_flagged.json",
            "2. Manually verify/correct suspicious labels",
            "3. Add more EVIDENCE examples (currently critically underrepresented)",
            "4. Add more WEATHER examples (currently underrepresented)",
            "5. Rebuild comprehensive_embeddings.npy after cleaning:",
            "   python scripts/rebuild_embeddings.py",
            "",
            "=" * 70,
        ]
    )

    report = "\n".join(report_lines)
    with open(REPORT_PATH, "w") as f:
        f.write(report)

    print(report)
    print("\nFiles written:")
    print(f"  {CLEAN_PATH}")
    print(f"  {FLAGGED_PATH}")
    print(f"  {REPORT_PATH}")


if __name__ == "__main__":
    main()
