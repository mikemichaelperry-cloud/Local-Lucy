"""Re-export for backward compatibility — implementation lives in router_py."""
from router_py.voice_tool import VoicePipeline, VoiceResult, VADConfig, AudioBuffer

__all__ = ["VoicePipeline", "VoiceResult", "VADConfig", "AudioBuffer"]
