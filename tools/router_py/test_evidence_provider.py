#!/usr/bin/env python3
"""Unit tests for evidence provider freshness and fallback behaviour."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent))

from providers.evidence import (
    _apply_evidence_freshness,
    _is_medical_vet_finance_evidence,
    _local_with_caveat_fallback,
    _parse_evidence_date,
    fetch_finance_evidence,
    fetch_trusted_evidence,
)


def test_is_medical_vet_finance_evidence():
    assert _is_medical_vet_finance_evidence({"class": "medical_context"})
    assert _is_medical_vet_finance_evidence({"provider": "trusted", "class": "veterinary_context"})
    assert _is_medical_vet_finance_evidence({"class": "finance_quote"})
    assert _is_medical_vet_finance_evidence(
        {"class": "trusted_general"}, route=MagicMock(evidence_reason="medical_context")
    )
    assert not _is_medical_vet_finance_evidence({"class": "wikipedia_general"})


def test_parse_evidence_date_from_source_age_days():
    parsed = _parse_evidence_date({"source_age_days": 100})
    assert parsed is not None
    age = (datetime.now(timezone.utc) - parsed).days
    assert age == 100


def test_parse_evidence_date_from_iso_string():
    parsed = _parse_evidence_date({"date": "2025-01-15"})
    assert parsed is not None
    assert parsed.year == 2025


def test_freshness_flags_stale_medical_evidence():
    evidence = {
        "context": "Old medical guidance",
        "class": "medical_context",
        "confidence": 0.9,
        "source_age_days": 500,
    }
    result = _apply_evidence_freshness(evidence)
    assert result["fresh"] is False
    assert result["source_age_days"] == 500
    assert result["confidence"] < 0.9


def test_freshness_leaves_recent_finance_evidence_fresh():
    evidence = {
        "context": "Current price",
        "class": "finance_quote",
        "confidence": 0.85,
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }
    result = _apply_evidence_freshness(evidence)
    assert result["fresh"] is True


def test_freshness_ignores_non_sensitive_domains():
    evidence = {
        "context": "Historical fact",
        "class": "wikipedia_general",
        "source_age_days": 500,
    }
    result = _apply_evidence_freshness(evidence)
    assert "fresh" not in result


def test_local_with_caveat_fallback_structure():
    fb = _local_with_caveat_fallback("What is metformin?")
    assert fb["fallback"] is True
    assert fb["suggested_action"] == "local_with_caveat"
    assert fb["context"] == ""
    assert fb["provider"] == "local"


def _fake_trusted_fetch_no_evidence(*args, **kwargs):
    return {"ok": False}


async def test_fetch_trusted_evidence_returns_fallback_when_no_evidence(monkeypatch):
    import sys

    fake_module = MagicMock(fetch_context=_fake_trusted_fetch_no_evidence)
    monkeypatch.setitem(sys.modules, "unverified_context_trusted", fake_module)
    route = MagicMock(intent_family="", evidence_reason="medical_context")
    result = await fetch_trusted_evidence("What are side effects of metformin?", route)
    assert result["fallback"] is True
    assert result["suggested_action"] == "local_with_caveat"


async def test_fetch_finance_evidence_returns_fallback_when_no_match():
    result = await fetch_finance_evidence("totally unrelated query")
    assert result["fallback"] is True
    assert result["suggested_action"] == "local_with_caveat"
