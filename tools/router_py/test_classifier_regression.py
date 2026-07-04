#!/usr/bin/env python3
"""Regression tests for the frozen routing validation corpus.

Loads data/evaluation/routing_validation_corpus.jsonl and asserts that
per-route recall and overall accuracy do not drop below the Phase 4 baseline.
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from router_py.classify import classify_intent, prewarm_router, select_route


# Phase 4 baseline measured after classifier hardening, hard negatives,
# stable-knowledge policy gate, and classifier threshold calibration.
BASELINE_RECALL = {
    "AUGMENTED": 0.38,
    "EPHEMERAL": 0.0,
    "EVIDENCE": 0.61,
    "FINANCE": 0.80,
    "LOCAL": 0.78,
    "NEWS": 0.89,
    "TIME": 0.78,
    "WEATHER": 0.77,
}

BASELINE_ACCURACY = 0.71


def _load_corpus() -> list[dict]:
    root = Path(__file__).resolve().parent.parent.parent
    path = root / "data" / "evaluation" / "routing_validation_corpus.jsonl"
    if not path.exists():
        pytest.skip(f"Validation corpus not found: {path}")
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _compute_metrics(corpus: list[dict]) -> tuple[float, dict[str, float]]:
    os.environ.setdefault("LUCY_SESSION_MEMORY", "0")
    prewarm_router()

    expected = []
    predicted = []
    for rec in corpus:
        classification = classify_intent(rec["query"])
        decision = select_route(classification, query=rec["query"])
        expected.append(rec["route"])
        predicted.append(decision.route)

    routes = sorted(set(expected) | set(predicted))
    confusion = {r: Counter() for r in routes}
    for e, p in zip(expected, predicted):
        confusion[e][p] += 1

    recall = {}
    for route in routes:
        tp = confusion[route][route]
        fn = sum(confusion[route][r] for r in routes if r != route)
        recall[route] = tp / (tp + fn) if (tp + fn) > 0 else 0.0

    accuracy = sum(1 for e, p in zip(expected, predicted) if e == p) / len(expected)
    return accuracy, recall


@pytest.fixture(scope="module")
def corpus_metrics():
    corpus = _load_corpus()
    return _compute_metrics(corpus)


def test_overall_accuracy(corpus_metrics):
    accuracy, _ = corpus_metrics
    assert (
        accuracy >= BASELINE_ACCURACY
    ), f"accuracy {accuracy:.4f} below baseline {BASELINE_ACCURACY}"


def test_per_route_recall(corpus_metrics):
    _, recall = corpus_metrics
    failures = []
    for route, baseline in BASELINE_RECALL.items():
        actual = recall.get(route, 0.0)
        if actual < baseline - 1e-6:
            failures.append(f"{route}: {actual:.4f} < {baseline}")
    assert not failures, "Per-route recall regressions:\n" + "\n".join(failures)
