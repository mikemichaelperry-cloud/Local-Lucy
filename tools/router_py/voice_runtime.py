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


class PTTController:
    """Push-to-talk controller for hold and tap modes.
    
    Hold mode: press starts recording, release stops recording.
    Tap mode: first tap starts recording, second tap stops recording.
    """
    
    def __init__(self, mode: str = "hold", max_seconds: float = 8.0):
        self.mode = mode
        self.max_seconds = max_seconds
        self._recording = False
        self._stop_event = asyncio.Event()
        self._lock = asyncio.Lock()
    
    async def press(self) -> bool:
        """Handle PTT press/tap. Returns True if recording should start."""
        async with self._lock:
            if self.mode == "hold":
                if not self._recording:
                    self._recording = True
                    self._stop_event.clear()
                    return True
                return False
            else:  # tap
                if not self._recording:
                    self._recording = True
                    self._stop_event.clear()
                    return True
                else:
                    # Second tap — stop recording
                    self._recording = False
                    self._stop_event.set()
                    return False
    
    async def release(self) -> bool:
        """Handle PTT release (hold mode only). Returns True if stop was triggered."""
        async with self._lock:
            if self.mode == "hold" and self._recording:
                self._recording = False
                self._stop_event.set()
                return True
            return False
    
    async def wait_for_stop(self, timeout: Optional[float] = None) -> bool:
        """Wait until stop is signaled or timeout. Returns True if stopped by signal."""
        try:
            await asyncio.wait_for(
                self._stop_event.wait(),
                timeout=timeout or self.max_seconds
            )
            return True
        except asyncio.TimeoutError:
            return False
    
    def is_recording(self) -> bool:
        return self._recording
    
    def reset(self):
        self._recording = False
        self._stop_event.clear()


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
        self._ptt = PTTController(mode=self.ptt_mode, max_seconds=self.max_seconds)
        
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
        # Signal PTT to stop if recording
        if self._ptt.is_recording():
            try:
                loop = asyncio.get_running_loop()
                loop.call_soon_threadsafe(self._ptt._stop_event.set)
            except RuntimeError:
                self._ptt._stop_event.set()
    
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
        """Record audio from microphone using PTT controller."""
        from voice_tool import VoicePipeline
        
        pipeline = VoicePipeline()
        self._ptt.reset()
        
        print("Recording... (speak now)")
        if self.ptt_mode == "hold":
            print("(Hold key/mouse to record, release to stop)")
        else:
            print("(Tap to start, tap again to stop)")
        
        try:
            # Start recording with no fixed duration — PTT controls stop
            record_task = asyncio.create_task(
                pipeline.record_audio(duration=None)
            )
            
            # Wait for PTT stop signal or timeout
            stopped_by_ptt = await self._ptt.wait_for_stop(timeout=float(self.max_seconds))
            
            if not stopped_by_ptt:
                print(f"[Recording timed out after {self.max_seconds}s]")
            
            # Cancel the recording pipeline to stop the subprocess
            pipeline.cancel()
            
            try:
                audio = await asyncio.wait_for(record_task, timeout=2.0)
            except asyncio.TimeoutError:
                print("[Recording did not stop cleanly]")
                return None
            
            if not audio or len(audio.data) == 0:
                print("[No audio captured]")
                return None
            
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
    
    async def ptt_press(self) -> bool:
        """Signal PTT press/tap. Returns True if recording should start."""
        return await self._ptt.press()
    
    async def ptt_release(self) -> bool:
        """Signal PTT release (hold mode). Returns True if stop was triggered."""
        return await self._ptt.release()
    
    def is_recording(self) -> bool:
        """Check if currently recording."""
        return self._ptt.is_recording()
    
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
