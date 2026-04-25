#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def title_place(text: str) -> str:
    words = [w for w in normalize_space(text).split(" ") if w]
    return " ".join(word[:1].upper() + word[1:] for word in words)


def is_compound_policy_query(text: str) -> bool:
    qn = (text or "").lower()
    has_climate = re.search(r"\b(climate policy|climate regulation|emissions policy|carbon policy)\b", qn) is not None
    has_ai = re.search(
        r"\b(ai safety|ai regulation|ai governance|technology regulation|technology governance|tech governance)\b",
        qn,
    ) is not None
    has_recent = re.search(r"\b(past week|this week|latest|recent|most significant developments?)\b", qn) is not None
    has_evidence = re.search(r"\b(with evidence|cite|citing|authoritative news sources?|trusted sources?)\b", qn) is not None
    has_synthesis = re.search(r"\b(interact|interaction|implications?|going forward|how .* interact)\b", qn) is not None
    return has_climate and has_ai and has_recent and has_evidence and has_synthesis


def build_candidates(query: str, mode: str) -> list[dict]:
    original = normalize_space(query)
    qn = original.lower()
    candidates = [{
        "adapter": "original",
        "strategy": "original",
        "confidence": "baseline",
        "confidence_score": 0.0,
        "planned_query": original,
    }]

    travel_match = re.search(
        r"\btravel advisory check for ([a-z][a-z .'-]{1,40}?)(?:\s+(?:today|now|at the moment))?\??$",
        qn,
        flags=re.IGNORECASE,
    )
    if travel_match and mode == "EVIDENCE":
        place = title_place(travel_match.group(1))
        candidates.append({
            "adapter": "travel",
            "strategy": "travel_advisory_check",
            "confidence": "high",
            "confidence_score": 0.92,
            "planned_query": f"Is it safe now to travel to {place}?",
        })

    combo_match = re.search(
        r"\b(?:best\s+combination\s+of|combine|combination\s+of)\s+([a-z0-9][a-z0-9 /()-]{0,40}?)\s*(?:\+|and|with|vs\.?|versus)\s*([a-z0-9][a-z0-9 /()-]{0,40}?)(?:\?|$)",
        qn,
        flags=re.IGNORECASE,
    )
    if not combo_match:
      combo_match = re.search(
          r"\b([a-z0-9][a-z0-9 /()-]{0,30}?)\s*\+\s*([a-z0-9][a-z0-9 /()-]{0,30}?)(?:\?|$)",
          qn,
          flags=re.IGNORECASE,
      )
    if combo_match and mode == "EVIDENCE":
        left = normalize_space(combo_match.group(1))
        right = normalize_space(combo_match.group(2))
        if left and right:
            candidates.extend([
                {
                    "adapter": "combination",
                    "strategy": "interaction_check",
                    "confidence": "medium",
                    "confidence_score": 0.78,
                    "planned_query": f"{left} {right} interaction",
                },
                {
                    "adapter": "combination",
                    "strategy": "safety_with",
                    "confidence": "medium",
                    "confidence_score": 0.74,
                    "planned_query": f"is {left} safe with {right}",
                },
            ])

    if mode == "EVIDENCE" and is_compound_policy_query(qn):
        candidates.extend([
            {
                "adapter": "compound_policy",
                "strategy": "climate_recent_global_policy",
                "confidence": "high",
                "confidence_score": 0.89,
                "planned_query": "recent global climate policy developments in past week",
            },
            {
                "adapter": "compound_policy",
                "strategy": "ai_recent_governance",
                "confidence": "high",
                "confidence_score": 0.87,
                "planned_query": "recent ai safety and ai regulation developments in past week",
            },
            {
                "adapter": "compound_policy",
                "strategy": "technology_regulation_overlap",
                "confidence": "medium",
                "confidence_score": 0.83,
                "planned_query": "technology regulation implications across climate policy and ai safety",
            },
        ])

    deduped = []
    seen = set()
    for candidate in sorted(candidates, key=lambda item: (-item["confidence_score"], item["adapter"], item["planned_query"])):
        key = candidate["planned_query"].lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def write_env(path: Path, payload: dict) -> None:
    best = payload.get("best_candidate") or {}
    lines = [
        f"PLANNER_ORIGINAL_QUERY={shell_quote(payload.get('original_query', ''))}",
        f"PLANNER_FIRED={shell_quote('true' if payload.get('planner_fired') else 'false')}",
        f"PLANNER_BEST_ADAPTER={shell_quote(best.get('adapter', ''))}",
        f"PLANNER_BEST_STRATEGY={shell_quote(best.get('strategy', ''))}",
        f"PLANNER_BEST_QUERY={shell_quote(best.get('planned_query', payload.get('original_query', '')))}",
        f"PLANNER_BEST_CONFIDENCE={shell_quote(best.get('confidence', 'baseline'))}",
        f"PLANNER_BEST_CONFIDENCE_SCORE={shell_quote(str(best.get('confidence_score', 0.0)))}",
        f"PLANNER_CANDIDATE_COUNT={shell_quote(str(len(payload.get('candidates', []))))}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_candidates(path: Path, payload: dict) -> None:
    lines = []
    for idx, candidate in enumerate(payload.get("candidates", []), start=1):
        lines.append("\t".join([
            str(idx),
            candidate.get("adapter", ""),
            candidate.get("strategy", ""),
            candidate.get("confidence", ""),
            str(candidate.get("confidence_score", 0.0)),
            candidate.get("planned_query", ""),
        ]))
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--env-out")
    parser.add_argument("--candidates-out")
    parser.add_argument("--json-out")
    args = parser.parse_args()

    candidates = build_candidates(args.query, (args.mode or "").upper())
    best = next((candidate for candidate in candidates if candidate["adapter"] != "original"), candidates[0] if candidates else None)
    payload = {
        "original_query": normalize_space(args.query),
        "planner_fired": any(candidate["adapter"] != "original" for candidate in candidates),
        "best_candidate": best or {},
        "candidates": candidates,
    }
    if args.env_out:
        write_env(Path(args.env_out), payload)
    if args.candidates_out:
        write_candidates(Path(args.candidates_out), payload)
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
