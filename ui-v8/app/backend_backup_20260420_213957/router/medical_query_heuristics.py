#!/usr/bin/env python3
import argparse

from core.medical_query_heuristics import (
    detect_human_medication_query,
    has_human_medication_topic_query,
    is_human_medication_high_risk_query,
    normalize_for_medical_match,
)

__all__ = [
    "detect_human_medication_query",
    "has_human_medication_topic_query",
    "is_human_medication_high_risk_query",
    "normalize_for_medical_match",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--is-human-medication-high-risk", dest="query", default=None)
    parser.add_argument("--detect-human-medication", dest="detect_query", default=None)
    args = parser.parse_args()

    if args.detect_query is not None:
        import json

        print(json.dumps(detect_human_medication_query(args.detect_query), separators=(",", ":"), sort_keys=True))
        return 0
    if args.query is None:
        return 2
    return 0 if is_human_medication_high_risk_query(args.query) else 1


if __name__ == "__main__":
    raise SystemExit(main())
