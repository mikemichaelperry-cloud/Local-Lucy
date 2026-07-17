#!/usr/bin/env python3
"""Regression tests for Gemma 4 model identity prompt."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from router_py.local_answer import _MODEL_IDENTITIES, get_self_knowledge


def test_gemma4_has_model_identity():
    """Gemma 4 must have its own identity entry instead of falling back to Llama 3."""
    assert "gemma4:12b-it-qat" in _MODEL_IDENTITIES, (
        "gemma4:12b-it-qat missing from _MODEL_IDENTITIES"
    )
    identity = get_self_knowledge("gemma4:12b-it-qat")
    assert "gemma4" in identity.lower(), f"Gemma 4 identity should mention gemma4, got: {identity}"
    assert "llama3.1" not in identity.lower(), (
        f"Gemma 4 identity should not mention llama3.1, got: {identity}"
    )
