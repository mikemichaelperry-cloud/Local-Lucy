#!/usr/bin/env python3
"""Tests for pipeline configuration helpers."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from router_py.pipeline.config import load_capability_flags


def test_load_capability_flags_defaults():
    flags = load_capability_flags()
    assert flags.source_attribution is False
    assert flags.suggest_web_escalation is False
    assert flags.auto_web_general_knowledge is False
    assert flags.trusted_sources_only_critical is True
