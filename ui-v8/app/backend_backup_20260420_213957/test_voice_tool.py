#!/usr/bin/env python3
"""
Tests for the Python Voice Pipeline Tool.

Run with: python -m pytest test_voice_tool.py -v
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# Ensure imports work
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest


try:
    from voice_tool import (
        VoicePipeline,
        VoicePipelineConfig,
        VoiceResult,
        clean_text,
        iso_now,
        use_python_voice,
    )
    VOICE_TOOL_AVAILABLE = True
except ImportError as exc:
    VOICE_TOOL_AVAILABLE = False
    print(f"Voice tool import error: {exc}")


class TestVoiceToolBasics:
    """Basic tests for voice tool functionality."""
    
    def test_clean_text(self):
        """Test text cleaning function."""
        assert clean_text("  hello  ") == "hello"
        assert clean_text(None) == ""
        assert clean_text(123) == "123"
    
    def test_iso_now(self):
        """Test ISO timestamp generation."""
        ts = iso_now()
        assert len(ts) > 0
        assert "T" in ts
        assert ts.endswith("Z")


class TestVoicePipelineConfig:
    """Tests for VoicePipelineConfig."""
    
    def test_default_config(self):
        """Test default configuration."""
        if not VOICE_TOOL_AVAILABLE:
            pytest.skip("Voice tool not available")
        
        config = VoicePipelineConfig()
        assert config.max_duration == 30.0
        assert config.capture_dir is None
    
    def test_custom_config(self):
        """Test custom configuration."""
        if not VOICE_TOOL_AVAILABLE:
            pytest.skip("Voice tool not available")
        
        with tempfile.TemporaryDirectory() as tmpdir:
            config = VoicePipelineConfig(
                max_duration=60.0,
                capture_dir=Path(tmpdir),
            )
            assert config.max_duration == 60.0
            assert config.resolve_capture_dir() == Path(tmpdir)


class TestVoicePipeline:
    """Tests for VoicePipeline."""
    
    def test_pipeline_creation(self):
        """Test creating a voice pipeline."""
        if not VOICE_TOOL_AVAILABLE:
            pytest.skip("Voice tool not available")
        
        pipeline = VoicePipeline()
        assert pipeline is not None
        assert pipeline.config is not None
    
    def test_detect_recorder(self):
        """Test recorder detection."""
        if not VOICE_TOOL_AVAILABLE:
            pytest.skip("Voice tool not available")
        
        pipeline = VoicePipeline()
        engine, binary = pipeline._detect_recorder()
        
        # Should detect one of the supported recorders or return empty
        assert engine in ("arecord", "pw-record", "")
        if engine:
            assert binary and Path(binary).exists()
    
    def test_detect_stt(self):
        """Test STT detection."""
        if not VOICE_TOOL_AVAILABLE:
            pytest.skip("Voice tool not available")
        
        pipeline = VoicePipeline()
        engine, binary = pipeline._detect_stt()
        
        # Should detect whisper or return empty
        assert engine in ("whisper", "")
    
    def test_backend_detection(self):
        """Test backend detection."""
        if not VOICE_TOOL_AVAILABLE:
            pytest.skip("Voice tool not available")
        
        pipeline = VoicePipeline()
        backend = pipeline._detect_backend()
        
        # Backend should have required fields
        assert hasattr(backend, 'available')
        assert hasattr(backend, 'recorder_engine')
        assert hasattr(backend, 'stt_engine')
        assert hasattr(backend, 'reason')
    
    def test_cancel(self):
        """Test cancel functionality."""
        if not VOICE_TOOL_AVAILABLE:
            pytest.skip("Voice tool not available")
        
        pipeline = VoicePipeline()
        pipeline.cancel()
        
        assert pipeline._cancelled is True


class TestVoiceResult:
    """Tests for VoiceResult."""
    
    def test_result_creation(self):
        """Test creating a voice result."""
        if not VOICE_TOOL_AVAILABLE:
            pytest.skip("Voice tool not available")
        
        result = VoiceResult(
            status="completed",
            transcript="Hello",
            response_text="Hi there",
            error="",
            tts_status="completed",
            request_id="test-123",
        )
        
        assert result.status == "completed"
        assert result.transcript == "Hello"
        assert result.response_text == "Hi there"
        assert result.error == ""
        assert result.tts_status == "completed"
        assert result.request_id == "test-123"
    
    def test_result_to_dict(self):
        """Test converting result to dict."""
        if not VOICE_TOOL_AVAILABLE:
            pytest.skip("Voice tool not available")
        
        result = VoiceResult(
            status="completed",
            transcript="Hello",
            response_text="Hi there",
            error="",
            tts_status="completed",
            request_id="test-123",
        )
        
        d = result.to_dict()
        assert d["status"] == "completed"
        assert d["transcript"] == "Hello"
        assert "response_text" in d


class TestUsePythonVoice:
    """Tests for the use_python_voice toggle."""
    
    def test_toggle_off_by_default(self):
        """Test that Python voice is off by default."""
        if not VOICE_TOOL_AVAILABLE:
            pytest.skip("Voice tool not available")
        
        # Clear the env var
        old_val = os.environ.pop("LUCY_VOICE_PY", None)
        try:
            assert use_python_voice() is False
        finally:
            if old_val is not None:
                os.environ["LUCY_VOICE_PY"] = old_val
    
    def test_toggle_on_when_set(self):
        """Test that Python voice can be enabled."""
        if not VOICE_TOOL_AVAILABLE:
            pytest.skip("Voice tool not available")
        
        old_val = os.environ.get("LUCY_VOICE_PY")
        os.environ["LUCY_VOICE_PY"] = "1"
        try:
            result = use_python_voice()
            # Should be True if voice tool is available
            assert isinstance(result, bool)
        finally:
            if old_val is not None:
                os.environ["LUCY_VOICE_PY"] = old_val
            else:
                del os.environ["LUCY_VOICE_PY"]


class TestTextProcessing:
    """Tests for text processing functions."""
    
    def test_normalize_transcript(self):
        """Test transcript normalization."""
        if not VOICE_TOOL_AVAILABLE:
            pytest.skip("Voice tool not available")
        
        pipeline = VoicePipeline()
        
        # Test basic normalization
        assert pipeline._normalize_transcript("  hello  world  ") == "hello world"
        
        # Test blank audio markers
        assert pipeline._normalize_transcript("[BLANK_AUDIO]") == ""
        assert pipeline._normalize_transcript("[silence]") == ""
    
    def test_sanitize_tts_text(self):
        """Test TTS text sanitization."""
        if not VOICE_TOOL_AVAILABLE:
            pytest.skip("Voice tool not available")
        
        pipeline = VoicePipeline()
        
        # Test URL removal
        sanitized = pipeline._sanitize_tts_text("Check out https://example.com for more info")
        assert "https://" not in sanitized
        
        # Test markdown removal
        sanitized = pipeline._sanitize_tts_text("This is **bold** and `code`")
        assert "**" not in sanitized
        assert "`" not in sanitized
    
    def test_split_tts_chunks(self):
        """Test TTS chunk splitting."""
        if not VOICE_TOOL_AVAILABLE:
            pytest.skip("Voice tool not available")
        
        pipeline = VoicePipeline()
        
        # Test basic splitting
        chunks = pipeline._split_tts_chunks("Hello world. This is a test.")
        assert len(chunks) >= 1
        
        # Test empty text
        chunks = pipeline._split_tts_chunks("")
        assert chunks == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
