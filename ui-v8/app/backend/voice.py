"""
Voice Module - Consolidated Single Source of Truth

Re-exports voice components from the authoritative snapshot location.
"""

from backend import (
    VoicePipeline,
    VoicePipelineConfig,
    VoiceResult,
    VADConfig,
    AudioBuffer,
)

__all__ = [
    'VoicePipeline',
    'VoicePipelineConfig',
    'VoiceResult',
    'VADConfig',
    'AudioBuffer',
]
