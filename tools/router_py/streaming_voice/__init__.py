"""Streaming voice pipeline for Local Lucy.

Streams TTS audio chunks as text is generated, eliminating delays.
Manages Kokoro TTS worker as a subprocess for optimal performance.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the repository root, tools tree, router_py package, and voice backends
# directory are importable, mirroring the path setup previously performed by the
# monolithic streaming_voice.py module.
ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(ROOT_DIR / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "tools"))

ROUTER_PY_DIR = Path(__file__).resolve().parent.parent
if str(ROUTER_PY_DIR) not in sys.path:
    sys.path.insert(0, str(ROUTER_PY_DIR))

VOICE_BACKENDS_DIR = ROUTER_PY_DIR.parent / "voice" / "backends"
if str(VOICE_BACKENDS_DIR) not in sys.path:
    sys.path.insert(0, str(VOICE_BACKENDS_DIR))

from .pipeline import StreamingVoicePipeline
from .text import _clean_for_tts, _strip_html_for_tts
from .worker import KokoroWorkerManager

__all__ = [
    "StreamingVoicePipeline",
    "KokoroWorkerManager",
    "_clean_for_tts",
    "_strip_html_for_tts",
]
