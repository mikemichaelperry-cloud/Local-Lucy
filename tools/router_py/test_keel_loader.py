#!/usr/bin/env python3
"""Tests for keel_loader.py."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest
from keel_loader import load_keel_status, load_keel_text

REPO_ROOT = Path(__file__).resolve().parents[2]


class TestKeelLoader:
    def test_load_keel_status_valid(self):
        status = load_keel_status()
        # In the test environment, keel/keel.yaml should exist
        if (REPO_ROOT / "keel" / "keel.yaml").exists():
            assert status["loaded"] is True
            assert status["path"].endswith("keel/keel.yaml")
            assert status["sha256"] is not None
            assert len(status["sha256"]) == 64
            assert status["rendered_text"].startswith("[KEEL")
            assert status["error"] is None
        else:
            pytest.skip("keel.yaml not present in this environment")

    def test_load_keel_text_returns_string(self):
        text = load_keel_text()
        assert isinstance(text, str)

    def test_load_keel_status_missing_file(self, monkeypatch, tmp_path):
        # Force a missing keel by overriding root candidates
        import keel_loader as kl

        orig_candidates = kl._ROOT_CANDIDATES
        try:
            kl._ROOT_CANDIDATES = [tmp_path]
            status = kl.load_keel_status()
            assert status["loaded"] is False
            assert status["error"] == "keel.yaml not found"
            assert status["rendered_text"] == ""
        finally:
            kl._ROOT_CANDIDATES = orig_candidates

    def test_load_keel_status_malformed_yaml(self, monkeypatch, tmp_path):
        import keel_loader as kl

        orig_candidates = kl._ROOT_CANDIDATES
        try:
            fake_keel = tmp_path / "keel" / "keel.yaml"
            fake_keel.parent.mkdir(parents=True, exist_ok=True)
            fake_keel.write_text("{not valid yaml: [", encoding="utf-8")
            kl._ROOT_CANDIDATES = [tmp_path]
            status = kl.load_keel_status()
            assert status["loaded"] is False
            assert "Malformed YAML" in (status["error"] or "")
        finally:
            kl._ROOT_CANDIDATES = orig_candidates

    def test_load_keel_status_empty_dict(self, monkeypatch, tmp_path):
        import keel_loader as kl

        orig_candidates = kl._ROOT_CANDIDATES
        try:
            fake_keel = tmp_path / "keel" / "keel.yaml"
            fake_keel.parent.mkdir(parents=True, exist_ok=True)
            fake_keel.write_text("", encoding="utf-8")
            kl._ROOT_CANDIDATES = [tmp_path]
            status = kl.load_keel_status()
            assert status["loaded"] is False
            assert "empty or malformed" in (status["error"] or "")
        finally:
            kl._ROOT_CANDIDATES = orig_candidates


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
