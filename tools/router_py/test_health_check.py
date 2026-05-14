#!/usr/bin/env python3
"""Tests for health_check.py."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

import health_check as hc


class TestHealthCheck:
    def test_check_router_model_missing(self, tmp_path):
        with patch.object(hc, "ROOT_DIR", tmp_path):
            result = hc._check_router_model()
            assert result["status"] == "unhealthy"
            assert "Missing" in result["detail"]

    def test_check_router_model_present(self, tmp_path):
        model_dir = tmp_path / "models" / "router"
        model_dir.mkdir(parents=True)
        (model_dir / "comprehensive_embeddings.npy").write_bytes(b"fake")
        (model_dir / "comprehensive_examples.json").write_text("[]")
        with patch.object(hc, "ROOT_DIR", tmp_path):
            result = hc._check_router_model()
            assert result["status"] == "healthy"
            assert "present" in result["detail"]

    def test_check_state_manager_missing(self, tmp_path):
        with patch.object(hc, "ROOT_DIR", tmp_path):
            result = hc._check_state_manager()
            assert result["status"] == "unhealthy"

    def test_check_state_manager_accessible(self, tmp_path):
        state_dir = tmp_path / "state"
        state_dir.mkdir(parents=True)
        db = state_dir / "lucy_state.db"
        import sqlite3
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY)")
        conn.close()
        with patch.object(hc, "ROOT_DIR", tmp_path):
            result = hc._check_state_manager()
            assert result["status"] == "healthy"

    @patch("urllib.request.urlopen")
    def test_check_ollama_healthy(self, mock_urlopen):
        resp = MagicMock()
        resp.read.return_value = b'{"models":[{"name":"qwen3"}]}'
        mock_urlopen.return_value.__enter__.return_value = resp
        result = hc._check_ollama()
        assert result["status"] == "healthy"
        assert "qwen3" in result["models"]

    @patch("urllib.request.urlopen")
    def test_check_ollama_unhealthy(self, mock_urlopen):
        mock_urlopen.side_effect = Exception("Connection refused")
        result = hc._check_ollama()
        assert result["status"] == "unhealthy"

    def test_run_health_check_overall(self):
        with patch.object(hc, "_check_ollama", return_value={"status": "healthy"}), \
             patch.object(hc, "_check_whisper", return_value={"status": "healthy"}), \
             patch.object(hc, "_check_router_model", return_value={"status": "healthy"}), \
             patch.object(hc, "_check_state_manager", return_value={"status": "healthy"}):
            result = hc.run_health_check()
            assert result["healthy"] is True
            assert len(result["checks"]) == 4

    def test_run_health_check_unhealthy(self):
        with patch.object(hc, "_check_ollama", return_value={"status": "unhealthy", "detail": "down"}), \
             patch.object(hc, "_check_whisper", return_value={"status": "healthy"}), \
             patch.object(hc, "_check_router_model", return_value={"status": "healthy"}), \
             patch.object(hc, "_check_state_manager", return_value={"status": "healthy"}):
            result = hc.run_health_check()
            assert result["healthy"] is False
