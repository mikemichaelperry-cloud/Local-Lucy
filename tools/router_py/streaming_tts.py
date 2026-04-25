#!/usr/bin/env python3
"""Streaming TTS playback for Kokoro.

Streams audio chunks as they're generated instead of waiting for full synthesis.
"""

import asyncio
import io
import subprocess
import wave
from pathlib import Path
from typing import Any, Optional


async def stream_kokoro_tts(
    text: str,
    voice: str = "af_heart",
    speed: float = 1.0,
    lang_code: str = "a",
    device: str = "cuda",
) -> None:
    """Stream Kokoro TTS audio chunks as they're generated.
    
    This starts playback immediately when the first audio chunk is ready,
    rather than waiting for the full synthesis to complete.
    
    Args:
        text: Text to synthesize
        voice: Voice identifier
        speed: Speech speed
        lang_code: Language code
        device: Device (cuda/cpu)
    """
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "voice" / "backends"))
    from kokoro_backend import get_pipeline, load_runtime_dependencies, DEFAULT_SAMPLE_RATE
    
    # Load dependencies
    _, np_module, _ = load_runtime_dependencies()
    
    # Get or create pipeline (this is cached)
    pipeline = get_pipeline(
        lang_code=lang_code,
        repo_id="hexgrad/Kokoro-82M",
        device=device,
    )
    
    # Start aplay process with stdin input for streaming
    aplay_proc = await asyncio.create_subprocess_exec(
        "aplay", "-q", "-",
        stdin=subprocess.PIPE,
    )
    
    # Write WAV header first
    wav_buffer = io.BytesIO()
    with wave.open(wav_buffer, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)  # 16-bit
        wav.setframerate(DEFAULT_SAMPLE_RATE)
    
    # Send WAV header to aplay
    header = wav_buffer.getvalue()
    aplay_proc.stdin.write(header)
    await aplay_proc.stdin.drain()
    
    # Stream audio chunks as they're generated
    chunk_count = 0
    for result in pipeline(text, voice=voice, speed=speed, split_pattern=r'\n+'):
        audio = getattr(result, "audio", None)
        if audio is not None:
            # Handle both numpy arrays and torch tensors
            try:
                audio_size = audio.size() if callable(audio.size) else audio.size
                # Convert torch.Size or numpy array size to int
                if hasattr(audio_size, '__len__'):
                    audio_size = int(audio_size[0]) if len(audio_size) > 0 else 0
                else:
                    audio_size = int(audio_size)
            except (TypeError, IndexError):
                audio_size = 0
            
            if audio_size > 0:
                # Convert to numpy if it's a torch tensor
                if hasattr(audio, 'numpy'):
                    audio = audio.numpy()
                elif hasattr(audio, 'cpu'):
                    audio = audio.cpu().numpy()
                
                # Convert float audio [-1, 1] to 16-bit PCM
                pcm_data = (audio * 32767).astype(np_module.int16).tobytes()
                aplay_proc.stdin.write(pcm_data)
                await aplay_proc.stdin.drain()
                chunk_count += 1
    
    # Close stdin to signal end of audio
    aplay_proc.stdin.close()
    await aplay_proc.wait()
    
    return chunk_count


async def prewarm_kokoro(
    voice: str = "af_heart",
    lang_code: str = "a",
    device: str = "cuda",
) -> bool:
    """Pre-warm Kokoro pipeline to avoid first-use latency.
    
    Call this at startup or when voice is enabled.
    
    Returns:
        True if pre-warming succeeded
    """
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "voice" / "backends"))
        from kokoro_backend import get_pipeline
        
        # Initialize pipeline (cached)
        _ = get_pipeline(
            lang_code=lang_code,
            repo_id="hexgrad/Kokoro-82M",
            device=device,
        )
        return True
    except Exception as e:
        print(f"Kokoro pre-warm failed: {e}")
        return False


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "prewarm":
        result = asyncio.run(prewarm_kokoro())
        print(f"Prewarm: {'OK' if result else 'FAILED'}")
    elif len(sys.argv) > 1:
        text = " ".join(sys.argv[1:])
        print(f"Synthesizing: {text}")
        chunks = asyncio.run(stream_kokoro_tts(text))
        print(f"Streamed {chunks} chunks")
    else:
        print("Usage: streaming_tts.py <text> or streaming_tts.py prewarm")
