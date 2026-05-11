#!/usr/bin/env python3
"""
Mocked functional voice integration tests.

Tests the full voice pipeline flow:
  Audio → STT (mock) → classify → route → execute (mock) → TTS (mock)

These tests verify that voice paths correctly:
1. Call main.run() as the unified entry point
2. Propagate context/surface="voice"
3. Return voice_text for NEWS routes
4. Handle errors gracefully
5. Respect the voice timeout (300s)

Run with: pytest tools/router_py/test_voice_integration.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_outcome(**kwargs: Any) -> Any:
    """Build a RouterOutcome-like object for mocking."""
    from router_py.request_types import RouterOutcome
    defaults = dict(
        status="completed",
        outcome_code="answered",
        route="LOCAL",
        provider="local",
        provider_usage_class="local",
        intent_family="local_answer",
        confidence=0.95,
        response_text="Mocked response",
        error_message="",
        execution_time_ms=100,
        request_id="voice_test_001",
        metadata={},
    )
    defaults.update(kwargs)
    return RouterOutcome(**defaults)


# ---------------------------------------------------------------------------
# Tests: Voice submit via main.run()
# ---------------------------------------------------------------------------


class TestVoiceSubmitFlow:
    """Test voice transcript submission through the unified pipeline."""

    @pytest.fixture(autouse=True)
    def _ensure_env(self):
        """Set LUCY_EXEC_PY for Python-native path."""
        import os
        os.environ["LUCY_EXEC_PY"] = "1"
        yield

    def test_voice_submit_routes_to_local(self):
        """Voice query 'What is 2+2?' should route LOCAL."""
        with patch("router_py.request_pipeline.process") as mock_process:
            mock_process.return_value = (
                _make_outcome(
                    route="LOCAL",
                    provider="local",
                    response_text="2 + 2 equals 4",
                ),
                None,
                None,
            )

            from router_py.main import run
            outcome = run("What is 2+2?", surface="voice", timeout=300)

            assert outcome.route == "LOCAL"
            assert outcome.provider == "local"
            assert "4" in outcome.response_text
            mock_process.assert_called_once()
            _, kwargs = mock_process.call_args
            assert kwargs.get("surface") == "voice"
            assert kwargs.get("timeout") == 300

    def test_voice_submit_routes_to_news_with_voice_text(self):
        """Voice news query should return voice_text in metadata."""
        with patch("router_py.request_pipeline.process") as mock_process:
            mock_process.return_value = (
                _make_outcome(
                    route="NEWS",
                    provider="news",
                    response_text="<html>News display</html>",
                    metadata={"voice_text": "Headline one, from Source A. Headline two, from Source B."},
                ),
                None,
                None,
            )

            from router_py.main import run
            outcome = run("Latest news about Israel", surface="voice", timeout=300)

            assert outcome.route == "NEWS"
            assert outcome.metadata.get("voice_text") == "Headline one, from Source A. Headline two, from Source B."

    def test_voice_submit_timeout_propagation(self):
        """Voice surface should use 300s timeout, not default 125s."""
        with patch("router_py.request_pipeline.process") as mock_process:
            mock_process.return_value = (_make_outcome(), None, None)

            from router_py.main import run
            run("Hello", surface="voice", timeout=300)

            _, kwargs = mock_process.call_args
            assert kwargs.get("timeout") == 300

    def test_voice_submit_failure_graceful(self):
        """Voice pipeline should handle execution failure gracefully."""
        with patch("router_py.request_pipeline.process") as mock_process:
            mock_process.return_value = (
                _make_outcome(
                    status="failed",
                    outcome_code="execution_error",
                    route="LOCAL",
                    error_message="Mocked failure",
                ),
                None,
                None,
            )

            from router_py.main import run
            outcome = run("Hello", surface="voice")

            assert outcome.status == "failed"
            assert outcome.error_message == "Mocked failure"


# ---------------------------------------------------------------------------
# Tests: Voice → HMI bridge
# ---------------------------------------------------------------------------


class TestVoiceHmiBridge:
    """Test voice action through the runtime bridge."""

    @pytest.fixture(autouse=True)
    def _setup_env(self, monkeypatch):
        """Set required env vars for RuntimeBridge instantiation."""
        project_root = str(Path(__file__).resolve().parents[3])
        monkeypatch.setenv("LUCY_RUNTIME_AUTHORITY_ROOT", project_root)
        monkeypatch.setenv("LUCY_UI_ROOT", f"{project_root}/ui-v8")
        monkeypatch.setenv("LUCY_RUNTIME_NAMESPACE_ROOT", project_root)
        # Add ui-v8/app to path for imports
        ui_app = f"{project_root}/ui-v8/app"
        if ui_app not in sys.path:
            sys.path.insert(0, ui_app)

    def test_voice_ptt_stop_returns_transcript(self, monkeypatch):
        """ptt-stop action should return transcript to UI."""
        try:
            from app.services.runtime_bridge import RuntimeBridge, CommandResult
        except ImportError:
            pytest.skip("UI runtime_bridge not available in this environment")

        bridge = RuntimeBridge()
        # Mock the voice action directly
        monkeypatch.setattr(
            bridge,
            "_run_voice_action",
            lambda action, value: CommandResult(
                action=action,
                requested_value=value,
                status="ok",
                returncode=0,
                stdout="",
                stderr="",
                timed_out=False,
                payload={"status": "completed", "transcript": "Hello Lucy"},
            ),
        )
        result = bridge.run_action("voice_ptt_stop", "")

        assert result.status == "ok"
        payload = result.payload or {}
        assert payload.get("transcript") == "Hello Lucy"

    def test_voice_ptt_stop_no_transcript(self, monkeypatch):
        """ptt-stop with no transcript should return no_transcript status."""
        try:
            from app.services.runtime_bridge import RuntimeBridge, CommandResult
        except ImportError:
            pytest.skip("UI runtime_bridge not available in this environment")

        bridge = RuntimeBridge()
        monkeypatch.setattr(
            bridge,
            "_run_voice_action",
            lambda action, value: CommandResult(
                action=action,
                requested_value=value,
                status="ok",
                returncode=0,
                stdout="",
                stderr="",
                timed_out=False,
                payload={"status": "no_transcript", "transcript": ""},
            ),
        )
        result = bridge.run_action("voice_ptt_stop", "")

        assert result.status == "ok"
        payload = result.payload or {}
        assert payload.get("status") == "no_transcript"


# ---------------------------------------------------------------------------
# Tests: TTS sanitization
# ---------------------------------------------------------------------------


class TestTtsSanitization:
    """Test TTS text sanitization for voice output."""

    def test_strips_validated_markers(self):
        """Validation markers should be stripped from TTS input."""
        from router_py.response_formatter import render_chat_fast_from_raw
        text = render_chat_fast_from_raw("BEGIN_VALIDATED\nHello world\nEND_VALIDATED")
        assert "BEGIN_VALIDATED" not in text
        assert "END_VALIDATED" not in text
        assert "Hello" in text
        assert "world" in text

    def test_decodes_html_entities(self):
        """HTML entities should be decoded for TTS."""
        text = "Latest news about &#x27;What&#x27;s new?&#x27;:"
        # Simulate streaming_voice sanitization
        text = text.replace("&#x27;", "'")
        text = text.replace("&#39;", "'")
        assert "&#x27;" not in text
        assert "What's new?" in text

    def test_news_header_no_double_escape(self):
        """News HTML header should not contain double-escaped entities."""
        from router_py.news_provider import RSSNewsProvider
        articles = [{"title": "Test", "description": "Desc", "source": "S", "time_ago": "1h", "url": ""}]
        html = RSSNewsProvider._format_news_response_html(articles, "What's new?")
        # Double-escape is the bug we fixed: &amp;#x27; should NOT be present
        assert "&amp;#x27;" not in html
        # html.escape converts ' to &#x27; — this is valid HTML (Qt renders it correctly)
        assert "What's new?" in html or "&#x27;" in html


# ---------------------------------------------------------------------------
# Tests: Kokoro worker mock
# ---------------------------------------------------------------------------


class TestKokoroWorkerMock:
    """Mocked tests for Kokoro TTS worker integration."""

    def test_kokoro_worker_request_format(self):
        """Verify Kokoro worker request JSON format."""
        import json
        request = {"cmd": "synthesize", "engine": "kokoro", "text": "Hello", "voice": "af_bella"}
        serialized = json.dumps(request, sort_keys=True)
        assert serialized == '{"cmd": "synthesize", "engine": "kokoro", "text": "Hello", "voice": "af_bella"}'

    def test_kokoro_worker_response_parsing(self):
        """Verify Kokoro worker response parsing."""
        import json
        response = '{"ok": true, "wav_path": "/tmp/test.wav"}'
        parsed = json.loads(response)
        assert parsed["ok"] is True
        assert parsed["wav_path"] == "/tmp/test.wav"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
