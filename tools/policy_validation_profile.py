#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import shlex
from pathlib import Path


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def query_shape(query: str) -> str:
    q = normalize(query)
    has_climate = re.search(r"\b(climate policy|climate regulation|emissions policy|carbon policy|global climate policy)\b", q) is not None
    has_ai = re.search(
        r"\b(ai|artificial intelligence|genai|llm|foundation models?|model evaluations?|ai safety|ai regulation|ai governance|technology regulation|technology governance|tech governance)\b",
        q,
    ) is not None
    has_fin = re.search(r"\b(financial regulation|financial policy|banking regulation|market regulation)\b", q) is not None
    if has_climate and has_ai and not has_fin:
        return "compound_climate_ai"
    if has_ai and not has_climate and not has_fin:
        return "single_ai"
    if has_climate and not has_ai and not has_fin:
        return "single_climate"
    if sum(1 for x in (has_climate, has_ai, has_fin) if x) >= 2:
        return "cross_domain_policy"
    return "none"


def requires_strict_specificity(query: str) -> bool:
    q = normalize(query)
    return re.search(
        r"\b(exact|exactly|specific|specify|deadline|deadlines|treaty|treaties|court|ruling|rulings|law number|article [0-9]+|section [0-9]+|which regulator|which country|which jurisdiction)\b",
        q,
    ) is not None


def key_family_for(key: str) -> str:
    if key.startswith("policy_climate_"):
        return "policy_climate"
    if key.startswith("policy_ai_gov_"):
        return "policy_ai_gov"
    if key.startswith("policy_regulation_"):
        return "policy_regulation"
    return ""


def support_from_pack(pack_dir: Path) -> tuple[dict[str, set[str]], set[str]]:
    families: dict[str, set[str]] = {
        "policy_climate": set(),
        "policy_ai_gov": set(),
        "policy_regulation": set(),
    }
    all_domains: set[str] = set()
    for meta_path in sorted(pack_dir.glob("item_*.meta")):
        key = ""
        dom = ""
        for raw in meta_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if raw.startswith("KEY="):
                key = raw.split("=", 1)[1].strip()
            elif raw.startswith("DOMAIN="):
                dom = raw.split("=", 1)[1].strip().lower()
        family = key_family_for(key)
        if not family or not dom:
            continue
        if dom.startswith("www."):
            dom = dom[4:]
        families.setdefault(family, set()).add(dom)
        all_domains.add(dom)
    return families, all_domains


def decide_allow(shape: str, families: dict[str, set[str]], all_domains: set[str]) -> tuple[bool, str]:
    climate_count = len(families.get("policy_climate", set()))
    ai_count = len(families.get("policy_ai_gov", set()))
    regulation_count = len(families.get("policy_regulation", set()))
    total_domains = len(all_domains)

    if shape == "single_ai":
        if ai_count >= 2 and total_domains >= 2:
            return True, "single_ai_two_domains"
        return False, "single_ai_under_supported"

    if shape == "single_climate":
        if climate_count >= 2 and total_domains >= 2:
            return True, "single_climate_two_domains"
        return False, "single_climate_under_supported"

    if shape == "compound_climate_ai":
        if climate_count >= 1 and ai_count >= 2 and regulation_count >= 1 and total_domains >= 4:
            return True, "compound_policy_multi_bucket_supported"
        return False, "compound_policy_missing_bucket_support"

    if shape == "cross_domain_policy":
        return False, "cross_domain_policy_kept_strict"

    return False, "not_policy_global_target"


def emit(assignments: dict[str, str]) -> None:
    for key in sorted(assignments.keys()):
        print(f"{key}={shlex.quote(str(assignments[key]))}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", required=True)
    ap.add_argument("--pack-dir", required=True)
    args = ap.parse_args()

    pack_dir = Path(args.pack_dir)
    shape = query_shape(args.query)
    if requires_strict_specificity(args.query):
        allow = False
        reason = "specific_target_requires_strict_support"
        families, all_domains = support_from_pack(pack_dir)
    else:
        families, all_domains = support_from_pack(pack_dir)
        allow, reason = decide_allow(shape, families, all_domains)

    assignments = {
        "POLICY_VALIDATION_PROFILE": "policy_global_recent" if shape != "none" else "",
        "POLICY_VALIDATION_APPLICABLE": "true" if shape != "none" else "false",
        "POLICY_VALIDATION_SHAPE": shape,
        "POLICY_VALIDATION_SUCCESS_FAMILIES": ",".join(
            family for family in ("policy_climate", "policy_ai_gov", "policy_regulation") if families.get(family)
        ),
        "POLICY_VALIDATION_UNIQUE_DOMAINS": str(len(all_domains)),
        "POLICY_VALIDATION_ALLOW_BOUNDED": "1" if allow else "0",
        "POLICY_VALIDATION_REASON": reason,
        "POLICY_VALIDATION_DOMAIN_COUNT_POLICY_CLIMATE": str(len(families.get("policy_climate", set()))),
        "POLICY_VALIDATION_DOMAIN_COUNT_POLICY_AI_GOV": str(len(families.get("policy_ai_gov", set()))),
        "POLICY_VALIDATION_DOMAIN_COUNT_POLICY_REGULATION": str(len(families.get("policy_regulation", set()))),
    }
    emit(assignments)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
