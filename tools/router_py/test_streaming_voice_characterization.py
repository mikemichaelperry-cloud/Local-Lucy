"""Characterization tests for the streaming_voice split.

These tests must pass against both the monolithic module and the split
package. They avoid model/audio dependencies.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "tools"))

pytestmark = [pytest.mark.static]


def test_streaming_voice_exports_pipeline_and_worker():
    """Public facade must expose StreamingVoicePipeline and KokoroWorkerManager."""
    from router_py.streaming_voice import KokoroWorkerManager, StreamingVoicePipeline

    assert isinstance(StreamingVoicePipeline, type)
    assert isinstance(KokoroWorkerManager, type)


def test_get_full_response_uses_main_run():
    """_get_full_response must route through router_py.main.run."""
    from router_py.streaming_voice import StreamingVoicePipeline

    source = inspect.getsource(StreamingVoicePipeline._get_full_response)
    assert "ExecutionEngine(" not in source, (
        "Voice streaming should not instantiate ExecutionEngine directly"
    )
    assert "from router_py.main import run" in source, (
        "Voice streaming should import and call the unified pipeline entry point"
    )


def _dummy_pipeline():
    """Return a StreamingVoicePipeline instance without running __init__."""
    from router_py.streaming_voice import StreamingVoicePipeline

    return object.__new__(StreamingVoicePipeline)


def test_clean_for_tts_strips_html():
    """_clean_for_tts must remove HTML tags from TTS input."""
    pipeline = _dummy_pipeline()

    raw = "<p>Hello <b>world</b>!</p><script>alert('x')</script>"
    cleaned = pipeline._clean_for_tts(raw)
    assert "<p>" not in cleaned
    assert "<b>" not in cleaned
    assert "</b>" not in cleaned
    assert "<script>" not in cleaned
    assert "Hello" in cleaned
    assert "world" in cleaned


def test_clean_for_tts_handles_sources_section():
    """_clean_for_tts should omit source catalog metadata from spoken text."""
    pipeline = _dummy_pipeline()

    raw = (
        "From current sources:\n"
        "- [example.com] (blog): Local Lucy is a desktop assistant.\n"
        "Source: example.com\n"
    )
    cleaned = pipeline._clean_for_tts(raw)
    assert "From current sources:" not in cleaned
    assert "Source:" not in cleaned
    assert "Local Lucy" in cleaned
