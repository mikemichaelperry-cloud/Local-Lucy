"""Shared response evaluation for the stage 09/11 scenario suites.

Single source of truth for concept/structure assertions. Substring checks on
free-form model output flake on phrasing; prefer required_answer_concepts_any
where the concept matters but the vocabulary does not (see DEC-016).
"""
from __future__ import annotations


def evaluate_response(scenario: dict, final_outcome) -> tuple[bool, list[str]]:
    """Evaluate a scenario's final outcome. Returns (passed, notes)."""
    raw_text = final_outcome.response_text or ""
    response_text = raw_text.lower()
    notes: list[str] = []
    passed = True

    expected_route = scenario.get("expected_route")
    if expected_route:
        allowed = expected_route if isinstance(expected_route, list) else [expected_route]
        if final_outcome.route not in allowed:
            notes.append(f"route expected {expected_route}, got {final_outcome.route}")
            passed = False

    for concept in scenario.get("required_answer_concepts", []):
        if concept.lower() not in response_text:
            notes.append(f"missing required concept: {concept}")
            passed = False

    any_concepts = scenario.get("required_answer_concepts_any", [])
    if any_concepts and not any(c.lower() in response_text for c in any_concepts):
        notes.append(f"missing required concept (any of: {any_concepts})")
        passed = False

    for claim in scenario.get("forbidden_answer_claims", []):
        if claim.lower() in response_text:
            notes.append(f"forbidden claim present: {claim}")
            passed = False

    if scenario.get("required_structure") == "haiku":
        lines = [line for line in raw_text.strip().splitlines() if line.strip()]
        if len(lines) != 3:
            notes.append("haiku does not have 3 lines")
            passed = False

    return passed, notes
