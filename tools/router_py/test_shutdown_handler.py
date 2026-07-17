#!/usr/bin/env python3
"""Tests for shutdown_handler.py."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from router_py import shutdown_handler as sh


class TestShutdownHandler:
    def test_register_closeable(self):
        sh._closeables.clear()
        obj = MagicMock()
        sh.register_closeable(obj)
        assert obj in sh._closeables

    def test_unregister_closeable(self):
        sh._closeables.clear()
        obj = MagicMock()
        sh.register_closeable(obj)
        sh.unregister_closeable(obj)
        assert obj not in sh._closeables

    def test_close_all_calls_close(self):
        sh._closeables.clear()
        sh._shutting_down = False
        obj = MagicMock()
        sh.register_closeable(obj)
        sh._close_all()
        obj.close.assert_called_once()
        assert sh._shutting_down is True

    def test_close_all_calls_callable(self):
        sh._closeables.clear()
        sh._shutting_down = False
        fn = MagicMock()
        # Ensure fn has no .close so the callable path is used
        del fn.close
        sh.register_closeable(fn)
        sh._close_all()
        fn.assert_called_once()

    def test_close_all_idempotent(self):
        sh._closeables.clear()
        sh._shutting_down = False
        obj = MagicMock()
        sh.register_closeable(obj)
        sh._close_all()
        sh._close_all()  # second call should be no-op
        obj.close.assert_called_once()

    def test_on_signal(self):
        with (
            patch.object(sh, "_close_all") as mock_close,
            patch("os.kill") as mock_kill,
            patch("signal.signal"),
        ):
            sh._on_signal(15, None)
            mock_close.assert_called_once()
            mock_kill.assert_called_once()

    def test_install_registers_atexit(self):
        with patch("atexit.register") as mock_atexit, patch("signal.signal") as mock_signal:
            sh.install()
            mock_atexit.assert_called_once_with(sh._close_all)
            assert mock_signal.call_count >= 2
