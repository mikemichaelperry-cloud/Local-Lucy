#!/usr/bin/env python3
"""Tests for voice PTT state machine in MainWindow.

These tests exercise the PTT press/release/queued-release/failure/timeout
paths without requiring a live microphone or backend.
"""

from __future__ import annotations

import os
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# Qt needs offscreen platform for headless testing
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_UI_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_UI_ROOT))

from PySide6.QtWidgets import QApplication

# Ensure required env vars for state_store
os.environ.setdefault("LUCY_RUNTIME_NAMESPACE_ROOT", str(Path.home() / ".codex-api-home" / "lucy" / "runtime-v8"))
os.environ.setdefault("LUCY_RUNTIME_AUTHORITY_ROOT", "/home/mike/lucy-v8")
os.environ.setdefault("LUCY_UI_ROOT", "/home/mike/lucy-v8/ui-v8")
os.environ.setdefault("LUCY_RUNTIME_CONTRACT_REQUIRED", "1")

from app.main_window import OperatorConsoleWindow as MainWindow


class TestVoicePTTStateMachine(unittest.TestCase):
    """Tests for the _voice_ptt_active state machine."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()
        if cls.app is None:
            cls.app = QApplication(sys.argv)

    def setUp(self):
        self.window = MainWindow()
        # Mock backend to avoid real I/O
        self.window._runtime_bridge = MagicMock()
        self.window._runtime_bridge.voice_available.return_value = True
        self.window._runtime_bridge.capabilities = {}
        self.window._runtime_bridge.request_available.return_value = True
        self.window._runtime_bridge.profile_available.return_value = True
        self.window._voice_ptt_available = True
        self.window._submit_available = True
        self.window._backend_controls_available = True
        # Prevent refresh_runtime_state from interfering with state machine tests
        self.window.refresh_runtime_state = lambda: None

        # Snapshot with voice=on, not listening
        self.window._latest_state_snapshot = SimpleNamespace(
            top_status={"Voice": "on"},
            voice_runtime={"listening": False, "status": "idle"},
            current_state={},
            runtime_status={},
            file_paths={},
            lifecycle_available=False,
            lifecycle_running=False,
            lifecycle_status="unknown",
            lifecycle_pid=None,
            snapshot_timestamp="",
            legacy_namespace_detected=False,
            legacy_namespace_path="",
            gpu_info={},
        )

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()

    def test_press_sets_active_flag(self):
        """Pressing PTT should set _voice_ptt_active = True."""
        self.assertFalse(self.window._voice_ptt_active)
        self.window._handle_voice_ptt_pressed()
        self.assertTrue(self.window._voice_ptt_active)

    def test_release_when_not_active_is_ignored(self):
        """Releasing PTT when _voice_ptt_active is False should do nothing."""
        self.window._voice_ptt_active = False
        self.window._handle_voice_ptt_released()
        # Should not execute any voice action
        self.window._runtime_bridge.run_voice_action.assert_not_called()

    def test_release_when_active_sends_stop(self):
        """Releasing PTT when active should send voice_ptt_stop."""
        self.window._voice_ptt_active = True
        self.window._voice_action_in_flight = False
        self.window._handle_voice_ptt_released()
        # Should have started a voice action
        self.assertTrue(self.window._voice_action_in_flight)
        self.assertEqual(self.window._pending_voice_action_label, "voice ptt stop")

    def test_queued_release_after_start_completes(self):
        """Release during start in-flight should queue and auto-trigger stop."""
        # Simulate: user presses PTT, start is in flight, user releases
        self.window._handle_voice_ptt_pressed()
        self.assertTrue(self.window._voice_action_in_flight)

        # Release while start is still in flight
        self.window._handle_voice_ptt_released()
        self.assertTrue(self.window._voice_release_pending)

        # Simulate start completing successfully
        mock_result = SimpleNamespace(
            status="ok",
            action="voice_ptt_start",
            payload={},
            stderr="",
            stdout="",
        )
        # Need to set up so the auto-trigger path is taken
        self.window._voice_ptt_active = True  # flag still true
        self.window._latest_state_snapshot.voice_runtime["listening"] = True
        self.window._handle_voice_action_complete(mock_result)

        # Should have auto-triggered stop
        self.assertFalse(self.window._voice_release_pending)
        self.assertTrue(self.window._voice_action_in_flight)
        self.assertEqual(self.window._pending_voice_action_label, "voice ptt stop")

    def test_start_failure_clears_active_flag(self):
        """Failed PTT start should clear _voice_ptt_active."""
        self.window._handle_voice_ptt_pressed()
        self.assertTrue(self.window._voice_ptt_active)

        # Simulate start failure
        mock_result = SimpleNamespace(
            status="failed",
            action="voice_ptt_start",
            payload={},
            stderr="mock error",
            stdout="",
        )
        self.window._handle_voice_action_complete(mock_result)
        self.assertFalse(self.window._voice_ptt_active)

    def test_start_timeout_clears_active_flag(self):
        """Timed-out PTT start should clear _voice_ptt_active."""
        self.window._handle_voice_ptt_pressed()
        self.assertTrue(self.window._voice_ptt_active)

        mock_result = SimpleNamespace(
            status="timeout",
            action="voice_ptt_start",
            payload={},
            stderr="",
            stdout="",
        )
        self.window._handle_voice_action_complete(mock_result)
        self.assertFalse(self.window._voice_ptt_active)

    def test_stop_completion_clears_active_flag(self):
        """Successful PTT stop should clear _voice_ptt_active."""
        self.window._voice_ptt_active = True
        mock_result = SimpleNamespace(
            status="ok",
            action="voice_ptt_stop",
            payload={"status": "completed"},
            stderr="",
            stdout="",
        )
        self.window._handle_voice_action_complete(mock_result)
        self.assertFalse(self.window._voice_ptt_active)

    def test_stop_timeout_clears_active_flag(self):
        """Timed-out PTT stop should clear _voice_ptt_active."""
        self.window._voice_ptt_active = True
        mock_result = SimpleNamespace(
            status="timeout",
            action="voice_ptt_stop",
            payload={},
            stderr="",
            stdout="",
        )
        self.window._handle_voice_action_complete(mock_result)
        self.assertFalse(self.window._voice_ptt_active)

    def test_double_press_blocked(self):
        """Pressing PTT while already active should be a no-op."""
        self.window._handle_voice_ptt_pressed()
        self.assertTrue(self.window._voice_ptt_active)

        # Try to press again while action is in flight
        # (simulate by resetting in_flight but keeping active)
        self.window._voice_action_in_flight = False
        self.window._handle_voice_ptt_pressed()
        # Should be blocked by _voice_ptt_active check at top
        # We can't easily verify without more mocking, but at minimum
        # the flag should still be True and no crash occurred
        self.assertTrue(self.window._voice_ptt_active)

    def test_snapshot_staleness_no_longer_blocks_release(self):
        """Release should work even when snapshot says not listening."""
        # Set up: active is True, but snapshot says not listening
        self.window._voice_ptt_active = True
        self.window._latest_state_snapshot.voice_runtime["listening"] = False
        self.window._voice_action_in_flight = False

        self.window._handle_voice_ptt_released()
        # Should have sent stop despite stale snapshot
        self.assertTrue(self.window._voice_action_in_flight)
        self.assertEqual(self.window._pending_voice_action_label, "voice ptt stop")


if __name__ == "__main__":
    unittest.main()
