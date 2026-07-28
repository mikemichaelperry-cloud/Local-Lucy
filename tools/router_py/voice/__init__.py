#!/usr/bin/env python3
"""Local Lucy voice processing package."""

# Core symbols that are always available (no heavy voice dependencies)
from router_py.voice.exceptions import (
    PlaybackError,
    RecordingError,
    SynthesisError,
    TranscriptionError,
    VoicePipelineError,
)
from router_py.voice.models import (
    AudioBuffer,
    TranscriptionResult,
    VADConfig,
    VoiceMetrics,
    VoiceResult,
)
from router_py.voice.utils import clean_text, iso_now

# Heavy voice pipeline is optional; gracefully degrade if deps are missing.
try:
    from router_py.voice.pipeline import VoicePipeline, quick_voice_interaction

    _voice_available = True
except ImportError:
    _voice_available = False

    class VoicePipeline:  # type: ignore
        def __init__(self, *args, **kwargs):
            raise ImportError("Voice pipeline dependencies are not available")

    def quick_voice_interaction(*args, **kwargs):  # type: ignore
        raise ImportError("Voice pipeline dependencies are not available")


__all__ = [
    "AudioBuffer",
    "TranscriptionResult",
    "VADConfig",
    "VoiceMetrics",
    "VoiceResult",
    "VoicePipeline",
    "quick_voice_interaction",
    "clean_text",
    "iso_now",
    "VoicePipelineError",
    "RecordingError",
    "TranscriptionError",
    "SynthesisError",
    "PlaybackError",
]
