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
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest

# Simple utilities — always available, independent of heavy deps
from router_py.voice_tool import clean_text, iso_now


try:
    from router_py.voice_tool import (
        VoicePipeline,
        VADConfig,
        VoiceResult,
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


class TestVoicePipeline:
    """Tests for VoicePipeline."""
    
    def test_pipeline_creation(self):
        """Test creating a voice pipeline."""
        if not VOICE_TOOL_AVAILABLE:
            pytest.skip("Voice tool not available")
        
        pipeline = VoicePipeline()
        assert pipeline is not None
        assert pipeline.vad_config is not None
    
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
            success=True,
            status="completed",
            transcript="Hello",
            response_text="Hi there",
            error_message="",
            tts_status="completed",
            request_id="test-123",
        )
        
        assert result.success is True
        assert result.status == "completed"
        assert result.transcript == "Hello"
        assert result.response_text == "Hi there"
        assert result.error_message == ""
        assert result.tts_status == "completed"
        assert result.request_id == "test-123"
    
    def test_result_to_dict(self):
        """Test converting result to dict."""
        if not VOICE_TOOL_AVAILABLE:
            pytest.skip("Voice tool not available")
        
        result = VoiceResult(
            success=True,
            status="completed",
            transcript="Hello",
            response_text="Hi there",
            error_message="",
            tts_status="completed",
            request_id="test-123",
        )
        
        d = result.to_dict()
        assert d["status"] == "completed"
        assert d["transcript"] == "Hello"
        assert "response_text" in d


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
    
    def test_strip_html_for_tts(self):
        """Test TTS HTML stripping."""
        if not VOICE_TOOL_AVAILABLE:
            pytest.skip("Voice tool not available")
        
        pipeline = VoicePipeline()
        
        # Test HTML tag removal
        sanitized = pipeline._strip_html_for_tts("Check out <a href='https://example.com'>link</a> for more info")
        assert "<a" not in sanitized
        
        # Test script removal
        sanitized = pipeline._strip_html_for_tts("Hello <script>alert(1)</script> world")
        assert "<script>" not in sanitized
        assert "alert" not in sanitized
    



if __name__ == "__main__":
    pytest.main([__file__, "-v"])
