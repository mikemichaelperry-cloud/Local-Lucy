#!/usr/bin/env python3
"""Export labeled routing data from Local Lucy state files for ModernBERT training.

Scans state/last_route.json, state/last_outcome.json, and state/namespaces/*
to build a labeled dataset of (query, intent_family, evidence_mode, route, policy).
"""

import json
import os
import re
from pathlib import Path
from typing import Any


def resolve_state_dirs() -> list[Path]:
    """Find all state directories (workspace + namespaces)."""
    roots = []
    namespace_root = Path(os.environ.get("LUCY_RUNTIME_NAMESPACE_ROOT", str(Path.home() / "lucy-v10")))
    roots.append(namespace_root / "state")
    
    namespaces_dir = namespace_root / "state" / "namespaces"
    if namespaces_dir.exists():
        for ns_dir in namespaces_dir.iterdir():
            if ns_dir.is_dir():
                roots.append(ns_dir)
    
    return [r for r in roots if r.exists()]


def parse_last_route(state_dir: Path) -> dict[str, Any] | None:
    """Read last_route.json or last_route.env and extract routing metadata."""
    json_path = state_dir / "last_route.json"
    env_path = state_dir / "last_route.env"
    
    if json_path.exists():
        try:
            return json.loads(json_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    
    if env_path.exists():
        # Parse KEY=VALUE env format
        result = {}
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                result[k.strip()] = v.strip().strip('"').strip("'")
        return result
    
    return None


def parse_last_outcome(state_dir: Path) -> dict[str, Any] | None:
    """Read last_outcome.env (extensive metadata)."""
    env_path = state_dir / "last_outcome.env"
    if not env_path.exists():
        return None
    
    result = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            result[k.strip()] = v.strip().strip('"').strip("'")
    return result


def parse_current_state(state_dir: Path) -> dict[str, Any] | None:
    """Read current_state.json for policy settings."""
    path = state_dir / "current_state.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def extract_examples(state_dirs: list[Path]) -> list[dict]:
    """Extract labeled examples from state directories."""
    examples = []
    seen_queries = set()
    
    for state_dir in state_dirs:
        route_data = parse_last_route(state_dir)
        outcome_data = parse_last_outcome(state_dir)
        current_state = parse_current_state(state_dir)
        
        if not route_data:
            continue
        
        query = route_data.get("QUERY") or route_data.get("query", "").strip()
        if not query or query in seen_queries:
            continue
        seen_queries.add(query)
        
        # Map legacy route labels to unified schema
        raw_route = route_data.get("ROUTE", "LOCAL")
        route = _normalize_route(raw_route)
        
        # Infer intent family from route + query content
        intent = _infer_intent(query, route, outcome_data or {})
        
        # Infer evidence mode from outcome flags
        evidence = _infer_evidence(query, outcome_data or {}, current_state or {})
        
        # Policy from current_state
        policy = _normalize_policy(current_state.get("augmentation_policy", "none") if current_state else "none")
        
        examples.append({
            "query": query,
            "labels": {
                "intent_family": intent,
                "evidence_mode": evidence,
                "route": route,
                "policy_override": policy,
            },
            "metadata": {
                "source": "historical",
                "confidence": 1.0,
                "state_dir": str(state_dir),
                "raw_route": raw_route,
            }
        })
    
    return examples


def _normalize_route(raw: str) -> str:
    """Normalize legacy route strings to unified schema."""
    mapping = {
        "local": "LOCAL",
        "local_with_fallback": "LOCAL_WITH_FALLBACK",
        "augmented": "AUGMENTED",
        "news": "NEWS",
        "time": "TIME",
        "clarify": "CLARIFY",
        "evidence": "AUGMENTED",
    }
    return mapping.get(raw.lower(), raw.upper())


def _normalize_policy(raw: str) -> str:
    """Normalize policy strings."""
    mapping = {
        "disabled": "disabled",
        "fallback_only": "fallback_only",
        "direct_allowed": "none",
        "none": "none",
    }
    return mapping.get(raw.lower(), "none")


def _infer_intent(query: str, route: str, outcome: dict) -> str:
    """Infer intent family from query content and routing outcome."""
    q_lower = query.lower()
    
    # Time queries
    time_patterns = [r"what time is it", r"current time", r"time in ", r"what's the time"]
    if any(re.search(p, q_lower) for p in time_patterns):
        return "time_query"
    
    # News queries
    news_patterns = [r"latest news", r"news about", r"headlines", r"what happened today"]
    if any(re.search(p, q_lower) for p in news_patterns) or route == "NEWS":
        return "news_request"
    
    # Medical
    medical_keywords = ["tadalafil", "sildenafil", "viagra", "cialis", "metformin", 
                        "insulin", "side effects", "treatment for", "dosage", "prescription"]
    if any(kw in q_lower for kw in medical_keywords):
        return "medical_inquiry"
    
    # Clarification triggers
    if len(query.split()) <= 3 or q_lower.endswith("?") and len(query) < 30:
        if route == "CLARIFY":
            return "clarification"
    
    # Creative writing
    creative_patterns = [r"write a (story|poem|song)", r"create a", r"imagine a"]
    if any(re.search(p, q_lower) for p in creative_patterns):
        return "creative_writing"
    
    # Current evidence
    evidence_patterns = [r"latest", r"current", r"recent", r"news", r"evidence", r"sources"]
    if any(re.search(p, q_lower) for p in evidence_patterns) or route in ("NEWS", "TIME"):
        return "current_evidence"
    
    # Technical
    technical_patterns = [r"how (do|does|to|can)", r"what is", r"explain", r"tutorial"]
    if any(re.search(p, q_lower) for p in technical_patterns):
        return "technical_explanation"
    
    # Default
    return "background_overview"


def _infer_evidence(query: str, outcome: dict, current_state: dict) -> str:
    """Infer evidence mode from query and state."""
    q_lower = query.lower()
    
    # Check if evidence was actually triggered in historical outcome
    if outcome.get("EVIDENCE_MODE") == "required" or current_state.get("evidence") == "on":
        return "required"
    
    # Medical / legal / conflict keywords
    evidence_keywords = [
        "evidence", "sources", "confirm", "verify", "prove", 
        "study", "research", "clinical trial", "data shows",
        "tadalafil", "sildenafil", "metformin", "insulin",
        "treatment", "dosage", "side effects",
    ]
    if any(kw in q_lower for kw in evidence_keywords):
        return "required"
    
    return "not_required"


def main():
    state_dirs = resolve_state_dirs()
    print(f"Found {len(state_dirs)} state directories")
    
    examples = extract_examples(state_dirs)
    print(f"Extracted {len(examples)} labeled examples")
    
    # Write to JSONL
    output_path = Path(__file__).parent / "data" / "raw" / "historical_routes.jsonl"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, "w", encoding="utf-8") as f:
        for ex in examples:
            f.write(json.dumps(ex, sort_keys=True) + "\n")
    
    print(f"Wrote {output_path}")
    
    # Print class distribution
    intents = {}
    routes = {}
    evidence = {}
    for ex in examples:
        intents[ex["labels"]["intent_family"]] = intents.get(ex["labels"]["intent_family"], 0) + 1
        routes[ex["labels"]["route"]] = routes.get(ex["labels"]["route"], 0) + 1
        evidence[ex["labels"]["evidence_mode"]] = evidence.get(ex["labels"]["evidence_mode"], 0) + 1
    
    print("\nClass distribution:")
    print("  Intent families:", dict(sorted(intents.items(), key=lambda x: -x[1])))
    print("  Routes:", dict(sorted(routes.items(), key=lambda x: -x[1])))
    print("  Evidence modes:", dict(sorted(evidence.items(), key=lambda x: -x[1])))


if __name__ == "__main__":
    main()
