#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List


CONFIDENCE_SCORES = {
    "high": 0.95,
    "medium": 0.75,
    "low": 0.55,
}


@dataclass
class Rule:
    adapter: str
    mode: str
    confidence: str
    pattern: str
    replacement: str


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def load_rules(path: Path) -> Dict[str, List[Rule]]:
    grouped: Dict[str, List[Rule]] = {}
    if not path.is_file():
        return grouped
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = raw_line.split("\t")
        if len(parts) < 5:
            continue
        rule = Rule(
            adapter=parts[0].strip(),
            mode=parts[1].strip().upper(),
            confidence=parts[2].strip().lower(),
            pattern=parts[3].strip(),
            replacement=parts[4].strip(),
        )
        grouped.setdefault(rule.adapter, []).append(rule)
    return grouped


def candidate_from_rules(query: str, mode: str, adapter: str, rules: List[Rule]) -> dict:
    rewritten = normalize_space(query)
    applied = []
    confidences = []
    for rule in rules:
        if rule.mode not in ("ANY", mode):
            continue
        next_query, count = re.subn(rule.pattern, rule.replacement, rewritten, flags=re.IGNORECASE)
        if count > 0:
            rewritten = normalize_space(next_query)
            applied.append({
                "pattern": rule.pattern,
                "replacement": rule.replacement,
                "count": count,
                "confidence": rule.confidence,
            })
            confidences.append(CONFIDENCE_SCORES.get(rule.confidence, 0.55))
    if not applied:
        return {}
    confidence_score = min(confidences, default=0.55)
    if confidence_score >= 0.95:
        confidence = "high"
    elif confidence_score >= 0.75:
        confidence = "medium"
    else:
        confidence = "low"
    return {
        "adapter": adapter,
        "domain": adapter,
        "normalized_query": rewritten,
        "confidence": confidence,
        "confidence_score": confidence_score,
        "applied_rules": applied,
    }


def build_candidates(query: str, mode: str, rules_by_adapter: Dict[str, List[Rule]]) -> List[dict]:
    original = normalize_space(query)
    candidates = [{
        "adapter": "original",
        "domain": "original",
        "normalized_query": original,
        "confidence": "baseline",
        "confidence_score": 0.0,
        "applied_rules": [],
    }]
    for adapter in sorted(rules_by_adapter):
        candidate = candidate_from_rules(original, mode, adapter, rules_by_adapter[adapter])
        if candidate:
            candidates.append(candidate)

    deduped = []
    seen = {}
    for candidate in sorted(candidates, key=lambda item: (-item["confidence_score"], item["adapter"], item["normalized_query"])):
        key = candidate["normalized_query"]
        if key in seen:
            continue
        seen[key] = True
        deduped.append(candidate)
    return deduped


def write_env(path: Path, payload: dict) -> None:
    best = payload.get("best_candidate") or {}
    candidates = payload.get("candidates") or []
    best_rules = "|".join(f"{item['pattern']}=>{item['replacement']}" for item in best.get("applied_rules", []))
    lines = [
        f"NORMALIZER_ORIGINAL_QUERY={shell_quote(payload.get('original_query', ''))}",
        f"NORMALIZER_DETECTOR_FIRED={shell_quote('true' if payload.get('detector_fired') else 'false')}",
        f"NORMALIZER_BEST_ADAPTER={shell_quote(best.get('adapter', ''))}",
        f"NORMALIZER_BEST_DOMAIN={shell_quote(best.get('domain', ''))}",
        f"NORMALIZER_BEST_QUERY={shell_quote(best.get('normalized_query', payload.get('original_query', '')))}",
        f"NORMALIZER_BEST_CONFIDENCE={shell_quote(best.get('confidence', 'baseline'))}",
        f"NORMALIZER_BEST_CONFIDENCE_SCORE={shell_quote(str(best.get('confidence_score', 0.0)))}",
        f"NORMALIZER_BEST_RULES={shell_quote(best_rules)}",
        f"NORMALIZER_CANDIDATE_COUNT={shell_quote(str(len(candidates)))}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_candidates(path: Path, payload: dict) -> None:
    lines = []
    for idx, candidate in enumerate(payload.get("candidates", []), start=1):
        rules = ",".join(f"{item['pattern']}=>{item['replacement']}" for item in candidate.get("applied_rules", []))
        fields = [
            str(idx),
            candidate.get("adapter", ""),
            candidate.get("domain", ""),
            candidate.get("confidence", ""),
            str(candidate.get("confidence_score", 0.0)),
            candidate.get("normalized_query", ""),
            rules,
        ]
        lines.append("\t".join(fields))
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--aliases-file")
    parser.add_argument("--env-out")
    parser.add_argument("--candidates-out")
    parser.add_argument("--json-out")
    args = parser.parse_args()

    conf_dir = Path(os.environ.get("LUCY_CONF_DIR") or str(Path(__file__).resolve().parents[1] / "config"))
    aliases_file = Path(args.aliases_file or str(conf_dir / "evidence_normalization_aliases_v1.tsv"))
    rules_by_adapter = load_rules(aliases_file)
    mode = (args.mode or "").upper()
    candidates = build_candidates(args.query, mode, rules_by_adapter)
    best = next((candidate for candidate in candidates if candidate["adapter"] != "original"), candidates[0] if candidates else None)
    payload = {
        "original_query": normalize_space(args.query),
        "mode": mode,
        "detector_fired": any(candidate["adapter"] != "original" for candidate in candidates),
        "best_candidate": best or {},
        "candidates": candidates,
    }

    if args.env_out:
        write_env(Path(args.env_out), payload)
    if args.candidates_out:
        write_candidates(Path(args.candidates_out), payload)
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    json.dump(payload, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
