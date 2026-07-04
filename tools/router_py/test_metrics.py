"""Tests for the JSONL metrics sink."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

import metrics


@pytest.fixture
def isolated_metrics_path(tmp_path: Path, monkeypatch):
    """Redirect metrics output to a temporary JSONL file."""
    path = tmp_path / "routing_metrics.jsonl"
    monkeypatch.setattr(metrics, "_METRICS_FILE", path)
    yield path


def _read_records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def test_record_request_writes_jsonl(isolated_metrics_path: Path):
    metrics.record_request(
        request_id="req-1",
        query="What is Python?",
        route="LOCAL",
        model="local-lucy",
        provider="local",
        confidence=0.85,
        latency_ms=120,
        outcome_code="answered",
    )
    records = _read_records(isolated_metrics_path)
    assert len(records) == 1
    record = records[0]
    assert record["type"] == "request"
    assert record["request_id"] == "req-1"
    assert record["query"] == "What is Python?"
    assert record["route"] == "LOCAL"
    assert record["model"] == "local-lucy"
    assert record["provider"] == "local"
    assert record["confidence"] == 0.85
    assert record["latency_ms"] == 120
    assert record["outcome_code"] == "answered"
    assert "ts" in record


def test_record_request_includes_error_and_extra(isolated_metrics_path: Path):
    metrics.record_request(
        request_id="req-err",
        query="test",
        route="NEWS",
        model="",
        provider="news",
        confidence=0.0,
        latency_ms=50,
        outcome_code="error",
        error="News provider returned no articles",
        extra={"status": "completed"},
    )
    records = _read_records(isolated_metrics_path)
    assert records[0]["error"] == "News provider returned no articles"
    assert records[0]["extra"] == {"status": "completed"}


def test_record_context_decision_and_usage(isolated_metrics_path: Path):
    metrics.record_context_decision(
        request_id="req-2",
        query="climate in Japan",
        kind="evidence",
        item_summary="Tourism in China...",
        score=0.2,
        accepted=False,
        reason="entity collision",
        extra={"provenance": "wikipedia"},
    )
    metrics.record_context_usage(
        request_id="req-2",
        context_kind="memory",
        used=1,
        total=3,
    )
    records = _read_records(isolated_metrics_path)
    assert len(records) == 2
    decision, usage = records
    assert decision["type"] == "context_decision"
    assert decision["kind"] == "evidence"
    assert decision["accepted"] is False
    assert decision["score"] == 0.2
    assert decision["reason"] == "entity collision"
    assert decision["item_summary"] == "Tourism in China..."
    assert usage["type"] == "context_usage"
    assert usage["used"] == 1
    assert usage["total"] == 3


def test_item_summary_is_truncated(isolated_metrics_path: Path):
    long_summary = "x" * 500
    metrics.record_context_decision(
        request_id="req-3",
        query="q",
        kind="evidence",
        item_summary=long_summary,
        score=0.5,
        accepted=True,
        reason="ok",
    )
    records = _read_records(isolated_metrics_path)
    assert len(records[0]["item_summary"]) <= 240


def test_record_failure_is_swallowed(isolated_metrics_path: Path, monkeypatch):
    """Metrics failures must never crash a request."""
    monkeypatch.setattr(
        metrics,
        "_write_line",
        lambda _path, _record: (_ for _ in ()).throw(RuntimeError("disk full")),
    )
    # The above lambda raises; record_request should catch it.
    metrics.record_request(
        request_id="req-fail",
        query="q",
        route="LOCAL",
        model="",
        provider="local",
        confidence=0.0,
        latency_ms=1,
        outcome_code="answered",
    )
    # If we reach this point, failure was swallowed.
    assert True


def test_concurrent_appends_are_safe(isolated_metrics_path: Path):
    import threading

    def writer(idx: int):
        for _ in range(20):
            metrics.record_request(
                request_id=f"req-{idx}",
                query="q",
                route="LOCAL",
                model="",
                provider="local",
                confidence=0.0,
                latency_ms=1,
                outcome_code="answered",
            )

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    records = _read_records(isolated_metrics_path)
    assert len(records) == 80
    for r in records:
        assert r["type"] == "request"


def test_metrics_file_is_created(isolated_metrics_path: Path):
    assert not isolated_metrics_path.exists()
    metrics.record_request(
        request_id="req-create",
        query="q",
        route="LOCAL",
        model="",
        provider="local",
        confidence=0.0,
        latency_ms=1,
        outcome_code="answered",
    )
    assert isolated_metrics_path.exists()
