#!/usr/bin/env python3
"""
Voice Runtime - Python implementation for interactive voice mode.

Replaces lucy_voice_ptt.sh with a fully Python-based voice interaction loop.
Uses streaming_voice.py for efficient TTS streaming.
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional

# Add paths for imports
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR / "tools"))
sys.path.insert(0, str(ROOT_DIR / "tools" / "router_py"))

try:
    from streaming_voice import StreamingVoicePipeline
    from voice_tool import VoicePipeline, AudioBuffer
    HAS_VOICE = True
except ImportError as e:
    print(f"Voice imports not available: {e}")
    HAS_VOICE = False


class VoiceRuntime:
    """Interactive voice runtime for Local Lucy."""
    
    def __init__(self):
        self.route_mode = os.environ.get("LUCY_VOICE_ROUTE_MODE", "auto")
        self.oneshot = os.environ.get("LUCY_VOICE_ONESHOT", "0") == "1"
        self.ptt_mode = os.environ.get("LUCY_VOICE_PTT_MODE", "hold")
        self.max_seconds = int(os.environ.get("LUCY_VOICE_MAX_SECONDS", "8"))
        self.enabled = os.environ.get("LUCY_VOICE_ENABLED", "1") == "1"
        
        self.pipeline: Optional[StreamingVoicePipeline] = None
        self._cancelled = False
        self._session_active = False
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self._handle_interrupt)
        signal.signal(signal.SIGTERM, self._handle_interrupt)
    
    def _handle_interrupt(self, signum, frame):
        """Handle Ctrl+C gracefully."""
        print("\n[Voice runtime interrupted]")
        self._cancelled = True
        if self.pipeline:
            self.pipeline.cancel()
        self._session_active = False
    
    def _print_banner(self):
        """Print voice mode banner."""
        mode_str = self.route_mode.upper()
        ptt_str = "TAP" if self.ptt_mode == "tap" else "HOLD"
        
        if self.oneshot:
            print(f"Voice mode ({mode_str}) - One-shot, exits after answer")
        else:
            print(f"Voice mode ({mode_str}) - Press Ctrl+C to return")
        print(f"PTT Mode: {ptt_str} | Max recording: {self.max_seconds}s")
        print()
    
    async def _record_audio(self) -> Optional[Path]:
        """Record audio from microphone."""
        from voice_tool import VoicePipeline
        
        pipeline = VoicePipeline()
        
        print("Recording... (speak now)")
        if self.ptt_mode == "hold":
            print("(Hold key/mouse to record, release to stop)")
        else:
            print("(Tap to start, tap again to stop)")
        
        try:
            # For now, use fixed duration recording
            # TODO: Implement VAD-based recording with hold/tap modes
            audio = await pipeline.record_audio(duration=float(self.max_seconds))
            
            # Save to temp file
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = Path(tmp.name)
            
            audio.save_to_file(tmp_path)
            return tmp_path
            
        except Exception as e:
            print(f"Recording error: {e}")
            return None
    
    async def _process_voice_interaction(self, audio_path: Path) -> bool:
        """Process a single voice interaction."""
        if not HAS_VOICE:
            print("Voice system not available")
            return False
        
        self.pipeline = StreamingVoicePipeline()
        
        print("Processing...")
        
        def on_transcript(text: str):
            if text:
                print(f"Transcript: {text}")
        
        def on_chunk(chunk: str):
            # Print response as it arrives
            print(chunk, end='', flush=True)
        
        try:
            result = await self.pipeline.stream_voice_interaction(
                audio_path,
                on_transcription=on_transcript,
                on_response_chunk=on_chunk,
            )
            
            print()  # Newline after response
            
            if result.get("success"):
                print(f"\n[Voice interaction complete]")
                return True
            else:
                error = result.get("error", "Unknown error")
                print(f"\n[Error: {error}]")
                return False
                
        except Exception as e:
            print(f"\n[Voice processing error: {e}]")
            return False
        finally:
            # Clean up audio file
            try:
                audio_path.unlink()
            except:
                pass
    
    async def run(self):
        """Main voice runtime loop."""
        if not self.enabled:
            print("Voice disabled by operator control.")
            return 0
        
        if not HAS_VOICE:
            print("Voice system not available. Missing dependencies.")
            return 1
        
        self._print_banner()
        self._session_active = True
        
        try:
            while self._session_active and not self._cancelled:
                # Record audio
                audio_path = await self._record_audio()
                
                if not audio_path:
                    if self.oneshot:
                        return 1
                    continue
                
                if self._cancelled:
                    break
                
                # Process the voice interaction
                success = await self._process_voice_interaction(audio_path)
                
                if self.oneshot:
                    return 0 if success else 1
                
                if self._cancelled:
                    break
                
                print()  # Blank line between interactions
                
        except KeyboardInterrupt:
            print("\n[Voice session ended]")
            return 0
        
        return 0


async def main():
    """Entry point for voice runtime."""
    runtime = VoiceRuntime()
    return await runtime.run()


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n[Interrupted]")
        sys.exit(0)
