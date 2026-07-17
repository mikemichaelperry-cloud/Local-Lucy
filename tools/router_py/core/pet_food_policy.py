#!/usr/bin/env python3
import importlib.util
from pathlib import Path
from typing import Dict, Optional


def _load_pet_food_module(root: str):
    path = Path(root) / "tools" / "knowledge" / "pet_food.py"
    spec = importlib.util.spec_from_file_location("lucy_pet_food_policy", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"unable to load pet_food module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def classify_pet_food_question(root: str, question: str) -> Dict[str, object]:
    module = _load_pet_food_module(root)
    return module.classify(question)


def resolve_pet_food_policy(root: str, question: str) -> Optional[Dict[str, object]]:
    result = classify_pet_food_question(root, question)
    if not isinstance(result, dict):
        return None
    matched = bool(result.get("matched"))
    if matched:
        return {
            "matched": True,
            "knowledge_path": "hit",
            "route_reason_override": "knowledge_pet_food_short_circuit",
            "outcome_code_override": "knowledge_short_circuit_hit",
            "local_response_text": str(result.get("answer") or ""),
        }
    return {
        "matched": False,
        "knowledge_path": "miss",
        "route_reason_override": "knowledge_pet_food_miss_fallback",
        "outcome_code_override": "medical_fetch_required_after_knowledge_miss",
        "classifier_reason": str(result.get("reason") or ""),
    }
