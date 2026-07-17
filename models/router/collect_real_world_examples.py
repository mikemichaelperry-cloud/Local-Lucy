#!/usr/bin/env python3
"""Mine real-world routing candidates from existing logs and state files.

Usage:
    python collect_real_world_examples.py [--compare] [--output PATH]

Output:
    A JSONL file where each line is a candidate example ready for human review
    and possible inclusion in comprehensive_examples.json.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROUTER_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = ROUTER_DIR.parent.parent
sys.path.insert(0, str(ROUTER_DIR))
sys.path.insert(0, str(PROJECT_ROOT))

# Optional: compare each candidate against the current router + policy gates.
try:
    from hybrid_router_v2 import HybridRouterV2

    _HAS_ROUTER = True
except Exception as exc:
    _HAS_ROUTER = False
    _ROUTER_ERROR = str(exc)

try:
    sys.path.insert(0, str(PROJECT_ROOT / "tools"))
    from policy import requires_evidence_mode
    from router_py.policy_router import PolicyRouter
    from router_py.request_types import ClassificationResult

    _HAS_POLICY = True
except Exception as exc:
    _HAS_POLICY = False
    _POLICY_ERROR = str(exc)

VALID_ROUTES = {
    "LOCAL",
    "AUGMENTED",
    "NEWS",
    "WEATHER",
    "TIME",
    "FINANCE",
    "EVIDENCE",
    "EPHEMERAL",
    "CLARIFY",
}

_ROUTE_RE = re.compile(
    r"\b(local|augmented|news|weather|time|finance|evidence|ephemeral|clarify)\b", re.I
)


def _normalise_query(query: str) -> str:
    return re.sub(r"\s+", " ", query.lower().strip().rstrip(".?"))


def _infer_intent_family(query: str, route: str) -> str:
    q = query.lower()
    if route in ("TIME",):
        return "time_query"
    if route in ("WEATHER",):
        return "weather_query"
    if route in ("NEWS",):
        return "news_request"
    if route in ("FINANCE",):
        return "finance_query"
    if route in ("EVIDENCE",):
        return "evidence_request"
    if any(kw in q for kw in ("who is", "who was", "what is", "what was", "how does", "explain")):
        return "background_overview"
    if any(kw in q for kw in ("how to", "how do i", "steps to", "guide for")):
        return "how_to"
    if any(kw in q for kw in ("opinion", "critique", "speculate", "what if")):
        return "local_answer"
    return "local_answer"


def _infer_evidence_mode(query: str, route: str, evidence_flag: str | None) -> str:
    if route == "EVIDENCE" or evidence_flag in ("on", "required"):
        return "required"
    q = query.lower()
    if any(kw in q for kw in ("evidence", "sources", "cite", "peer-reviewed", "study", "studies")):
        return "required"
    return "not_required"


def _extract_route_from_history(entry: dict[str, Any]) -> str | None:
    route = entry.get("route", {})
    if isinstance(route, dict):
        mode = route.get("final_mode") or route.get("mode")
    else:
        mode = str(route)
    if mode:
        match = _ROUTE_RE.search(mode)
        if match:
            return match.group(1).upper()
    return None


def _iter_request_history(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    candidates: list[dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            query = (entry.get("request_text") or "").strip()
            if not query:
                continue
            route = _extract_route_from_history(entry)
            if route not in VALID_ROUTES:
                continue
            if entry.get("status") != "completed":
                continue
            if entry.get("error"):
                continue
            control = entry.get("control_state") or {}
            outcome = entry.get("outcome") or {}
            candidates.append(
                {
                    "query": query,
                    "route": route,
                    "source": str(path.relative_to(PROJECT_ROOT)),
                    "intent": entry.get("intent", ""),
                    "evidence_flag": control.get("evidence"),
                    "outcome_code": outcome.get("outcome_code", ""),
                    "augmented_provider_used": outcome.get("augmented_provider_used", ""),
                }
            )
    return candidates


def _iter_router_decisions(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    candidates: list[dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            query = (entry.get("query") or "").strip()
            if not query:
                continue
            route = (entry.get("route") or "").upper()
            if route not in VALID_ROUTES:
                continue
            candidates.append(
                {
                    "query": query,
                    "route": route,
                    "source": str(path.relative_to(PROJECT_ROOT)),
                    "intent": entry.get("intent", ""),
                    "evidence_flag": None,
                    "outcome_code": "",
                    "augmented_provider_used": entry.get("provider", ""),
                }
            )
    return candidates


def _discover_sources() -> list[Path]:
    sources: list[Path] = []
    main_history = PROJECT_ROOT / "state" / "request_history.jsonl"
    if main_history.exists():
        sources.append(main_history)
    burnin = PROJECT_ROOT / "burn_in_logs" / "router_decisions.jsonl"
    if burnin.exists():
        sources.append(burnin)
    namespaces_root = PROJECT_ROOT / "state" / "namespaces"
    if namespaces_root.is_dir():
        for ns_dir in namespaces_root.iterdir():
            hist = ns_dir / "request_history.jsonl"
            if hist.exists():
                sources.append(hist)
    return sources


def _build_candidate(
    raw: dict[str, Any],
    router: HybridRouterV2 | None,
    policy: PolicyRouter | None,
) -> dict[str, Any]:
    query = raw["query"]
    route = raw["route"]
    intent_family = _infer_intent_family(query, route)
    evidence_mode = _infer_evidence_mode(query, route, raw.get("evidence_flag"))

    current_prediction: str | None = None
    review = False
    review_reason: str | None = None

    if router is not None:
        try:
            if policy is not None:
                _, evidence_reason = requires_evidence_mode(query, context={})
                classification = ClassificationResult(
                    intent="ask",
                    intent_family=intent_family,
                    evidence_reason=evidence_reason,
                )
                decision = policy.apply(query, classification, context={})
                if decision is not None:
                    current_prediction = decision.route
                else:
                    current_prediction = router.predict(query).get("route")
            else:
                current_prediction = router.predict(query).get("route")
            if current_prediction != route:
                review = True
                review_reason = (
                    f"current router predicts {current_prediction}; logged route was {route}"
                )
        except Exception as exc:
            review = True
            review_reason = f"router prediction failed: {exc}"

    return {
        "query": query,
        "labels": {
            "intent_family": intent_family,
            "evidence_mode": evidence_mode,
            "route": route,
            "policy_override": "none",
        },
        "metadata": {
            "source": raw["source"],
            "original_intent": raw.get("intent", ""),
            "original_outcome_code": raw.get("outcome_code", ""),
            "original_provider": raw.get("augmented_provider_used", ""),
            "current_prediction": current_prediction,
            "review": review,
            "review_reason": review_reason,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect real-world routing candidates.")
    parser.add_argument(
        "--compare",
        action="store_true",
        help="Compare each candidate against the current router (slower, loads MiniLM).",
    )
    parser.add_argument(
        "--output",
        default=str(ROUTER_DIR / "real_world_candidates.jsonl"),
        help="Output JSONL path",
    )
    args = parser.parse_args()

    sources = _discover_sources()
    print(f"Discovered {len(sources)} log/state sources")
    for src in sources:
        print(f"  - {src.relative_to(PROJECT_ROOT)}")

    raw_rows: list[dict[str, Any]] = []
    for src in sources:
        if "request_history" in src.name:
            raw_rows.extend(_iter_request_history(src))
        elif "router_decisions" in src.name:
            raw_rows.extend(_iter_router_decisions(src))

    # Deduplicate by normalised query, keeping the most recent source if conflicting.
    seen: dict[str, dict[str, Any]] = {}
    for row in raw_rows:
        key = _normalise_query(row["query"])
        if not key:
            continue
        existing = seen.get(key)
        if existing is None or row["source"] > existing["source"]:
            seen[key] = row

    unique_rows = list(seen.values())
    print(f"\n{len(raw_rows)} raw rows -> {len(unique_rows)} unique queries")

    router: HybridRouterV2 | None = None
    policy: PolicyRouter | None = None
    if args.compare:
        if _HAS_ROUTER:
            print("Loading current router for comparison...")
            router = HybridRouterV2()
        else:
            print(f"WARNING: cannot load router for comparison: {_ROUTER_ERROR}", file=sys.stderr)
        if _HAS_POLICY:
            policy = PolicyRouter()
        else:
            print(f"WARNING: cannot load policy router: {_POLICY_ERROR}", file=sys.stderr)

    candidates = [_build_candidate(row, router, policy) for row in unique_rows]
    candidates.sort(key=lambda c: (not c["metadata"]["review"], c["query"]))

    output_path = Path(args.output)
    with open(output_path, "w", encoding="utf-8") as f:
        for cand in candidates:
            f.write(json.dumps(cand, ensure_ascii=False) + "\n")

    route_counts = Counter(c["labels"]["route"] for c in candidates)
    review_count = sum(1 for c in candidates if c["metadata"]["review"])

    print(f"\nWrote {len(candidates)} candidates to {output_path}")
    print("\nRoute distribution:")
    for route, count in route_counts.most_common():
        print(f"  {route}: {count}")
    print(f"\nFlagged for review: {review_count}")
    if review_count:
        print("Top review examples:")
        for c in candidates[:5]:
            if c["metadata"]["review"]:
                print(
                    f"  - {c['query'][:70]:70s} "
                    f"logged={c['labels']['route']} "
                    f"current={c['metadata']['current_prediction']}"
                )


if __name__ == "__main__":
    main()
