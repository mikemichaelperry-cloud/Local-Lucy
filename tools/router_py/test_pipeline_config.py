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
    assert flags.auto_web_allowed_domains == ()


def test_load_capability_flags_env_list(monkeypatch):
    monkeypatch.setenv("LUCY_AUTO_WEB_ALLOWED_DOMAINS", "example.com, wikipedia.org ,")
    flags = load_capability_flags()
    assert flags.auto_web_allowed_domains == ("example.com", "wikipedia.org")
