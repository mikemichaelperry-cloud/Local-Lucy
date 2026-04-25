#!/usr/bin/env python3
"""Helper script to synthesize text chunks using Kokoro.

Called as subprocess from streaming_voice.py when Kokoro is not available
in the calling Python environment.
"""

import os
import sys
import struct
from pathlib import Path

# Suppress HF Hub warnings - CRITICAL: prevent stdout corruption of PCM audio
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
# Redirect stderr to suppress HuggingFace auth warnings
import warnings
warnings.filterwarnings("ignore")
import logging
logging.getLogger("transformers").setLevel(logging.ERROR)
logging.getLogger("huggingface_hub").setLevel(logging.ERROR)

# Add paths for Kokoro
sys.path.insert(0, str(Path(__file__).parent.parent / "voice" / "backends"))

import numpy as np
from kokoro_backend import get_pipeline, load_runtime_dependencies, DEFAULT_SAMPLE_RATE


def resample_audio(audio: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
    """Resample audio from orig_sr to target_sr using simple linear interpolation."""
    if orig_sr == target_sr:
        return audio
    
    # Calculate resampling ratio
    ratio = target_sr / orig_sr
    new_length = int(len(audio) * ratio)
    
    # Use scipy if available, otherwise simple interpolation
    try:
        from scipy import signal
        return signal.resample(audio, new_length)
    except ImportError:
        # Simple linear interpolation fallback
        old_indices = np.arange(len(audio))
        new_indices = np.linspace(0, len(audio) - 1, new_length)
        return np.interp(new_indices, old_indices, audio)


def synthesize_chunk(text: str, voice: str = "af_nicole", speed: float = 1.0):
    # NOTE: Kokoro outputs at 24kHz, but we need 22050 Hz for Piper compatibility.
    # The streaming_voice.py aplay is configured for 22050 Hz.
    """Synthesize text and output raw PCM data to stdout.
    
    Data format: 16-bit signed PCM, mono, 22050 Hz (Piper-compatible)
    """
    # Load Kokoro
    _, np_module, _ = load_runtime_dependencies()
    pipeline = get_pipeline(lang_code="a", repo_id="hexgrad/Kokoro-82M", device="cuda")
    
    # Generate audio chunks
    for result in pipeline(text, voice=voice, speed=speed, split_pattern=r'\n+'):
        audio = getattr(result, "audio", None)
        if audio is not None:
            # Convert to numpy
            if hasattr(audio, 'numpy'):
                audio = audio.numpy()
            elif hasattr(audio, 'cpu'):
                audio = audio.cpu().numpy()
            
            # Resample from Kokoro's 24kHz to 22050 Hz for Piper compatibility
            if audio.dtype != np.float32:
                audio = audio.astype(np.float32)
            audio_22050 = resample_audio(audio, DEFAULT_SAMPLE_RATE, 22050)
            
            # Convert to PCM and write to stdout
            pcm_data = (audio_22050 * 32767).astype(np.int16).tobytes()
            sys.stdout.buffer.write(pcm_data)
            sys.stdout.buffer.flush()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("text", help="Text to synthesize")
    parser.add_argument("--voice", default="af_bella")
    parser.add_argument("--speed", type=float, default=1.0)
    args = parser.parse_args()
    
    synthesize_chunk(args.text, args.voice, args.speed)
