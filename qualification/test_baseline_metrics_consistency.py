#!/usr/bin/env python3
"""Verify that baseline_metrics.json counts are internally consistent."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _load_metrics() -> dict:
    path = Path(__file__).with_name("results") / "baseline_metrics.json"
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


@pytest.mark.parametrize(
    "split_name",
    ["validation", "locked_holdout", "combined"],
)
def test_reported_accuracy_matches_count_ratio(split_name: str) -> None:
    metrics = _load_metrics()[split_name]
    correct = metrics["correct"]
    total = metrics["total_cases"]
    accuracy = metrics["overall_accuracy"]
    assert accuracy == pytest.approx(correct / total, rel=1e-9)


@pytest.mark.parametrize(
    "split_name",
    ["validation", "locked_holdout", "combined"],
)
def test_per_route_counts_are_consistent(split_name: str) -> None:
    metrics = _load_metrics()[split_name]
    total = metrics["total_cases"]
    per_route = metrics["per_route"]
    tp_sum = sum(r["tp"] for r in per_route.values())
    fn_sum = sum(r["fn"] for r in per_route.values())
    # TP + FN must equal the number of cases (each case has one expected route)
    assert tp_sum + fn_sum == total
