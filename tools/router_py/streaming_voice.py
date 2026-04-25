#!/usr/bin/env python3
"""Streaming voice pipeline for Local Lucy.

Streams TTS audio chunks as text is generated, eliminating delays.
Manages Kokoro TTS worker as a subprocess for optimal performance.
"""

import asyncio
import audioop
import json
import math
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import AsyncIterator, Optional

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "voice" / "backends"))


def _get_audio_levels_file() -> Path:
    """Get path to audio levels file for VU meter."""
    runtime_dir = Path(os.environ.get("LUCY_RUNTIME_NAMESPACE_ROOT", 
        Path.home() / ".codex-api-home/lucy/runtime-v8"))
    return runtime_dir / "state" / "voice_audio_levels.json"


def _read_existing_input_level(levels_file: Path) -> int:
    """Read existing input_level from file if present."""
    try:
        if levels_file.exists():
            with open(levels_file, 'r') as f:
                data = json.load(f)
                return int(data.get("input_level", 0))
    except Exception:
        pass
    return 0


def _write_output_level(level: int, levels_file: Path) -> None:
    """Write output audio level to file (preserves input_level)."""
    import logging
    logger = logging.getLogger("streaming_voice")
    try:
        # Ensure parent directory exists
        levels_file.parent.mkdir(parents=True, exist_ok=True)
        
        input_level = _read_existing_input_level(levels_file)
        data = {
            "input_level": input_level,
            "output_level": level,
            "timestamp": time.time(),
            "playing": level > 0,
        }
        # Atomic write
        tmp_file = levels_file.with_suffix('.tmp')
        with open(tmp_file, 'w') as f:
            json.dump(data, f)
        tmp_file.rename(levels_file)
        logger.debug(f"Wrote output_level={level} to {levels_file}")
    except Exception as e:
        logger.debug(f"Level write error: {e}")


def _calculate_pcm_level(pcm_data: bytes) -> int:
    """Calculate audio level (0-100) from PCM data using peak detection."""
    if not pcm_data:
        return 0
    try:
        # Use max (peak) level instead of RMS for more dynamic response
        # This better follows speech patterns as it catches transients
        sample_count = len(pcm_data) // 2  # 16-bit samples
        max_val = 0
        for i in range(sample_count):
            # Extract 16-bit signed sample
            sample = pcm_data[i*2] | (pcm_data[i*2 + 1] << 8)
            if sample > 32767:
                sample -= 65536
            abs_sample = abs(sample)
            if abs_sample > max_val:
                max_val = abs_sample
        
        if max_val > 0:
            # Convert to dB scale 0-100
            # 16-bit max is 32767, map -60dB to 0% and 0dB to 100%
            db = 20 * math.log10(max_val / 32767.0)
            level = int((db + 60) / 60 * 100)
            return max(0, min(100, level))
    except Exception:
        pass
    return 0


def _analyze_pcm_levels(pcm_data: bytes, sample_rate: int = 22050, chunk_duration_ms: float = 30.0) -> list[int]:
    """Analyze PCM data into level chunks for VU meter.
    
    Args:
        pcm_data: Raw PCM data (16-bit mono)
        sample_rate: Sample rate in Hz
        chunk_duration_ms: Duration of each chunk in milliseconds
        
    Returns:
        List of audio levels (0-100) for each chunk
    """
    if not pcm_data:
        return []
    
    levels = []
    sample_width = 2  # 16-bit = 2 bytes
    chunk_samples = int(sample_rate * chunk_duration_ms / 1000)
    chunk_bytes = chunk_samples * sample_width
    
    # Process PCM data in chunks
    offset = 0
    while offset < len(pcm_data):
        chunk = pcm_data[offset:offset + chunk_bytes]
        if len(chunk) < sample_width:
            break
        
        level = _calculate_pcm_level(chunk)
        levels.append(level)
        offset += chunk_bytes
    
    return levels


def _get_ui_v8_python() -> str:
    """Get path to ui-v8 Python which has Kokoro installed."""
    root = Path(__file__).parent.parent.parent.parent.parent
    return str(root / "ui-v8" / ".venv" / "bin" / "python3")


def _detect_kokoro_availability() -> bool:
    """Check if Kokoro is available in current Python."""
    try:
        import kokoro
        from kokoro_backend import get_pipeline
        return True
    except ImportError:
        return False


class KokoroWorkerManager:
    """Manages Kokoro TTS worker subprocess lifecycle."""
    
    def __init__(self, socket_path: Path):
        self.socket_path = socket_path
        self.process: Optional[subprocess.Popen] = None
        self._lock = asyncio.Lock()
        
    async def ensure_running(self, timeout: float = 10.0) -> bool:
        """Start worker if not running."""
        async with self._lock:
            # Check if already running and responsive
            if self._is_responsive():
                return True
            
            # Clean up stale socket
            if self.socket_path.exists():
                self.socket_path.unlink()
            
            # Start worker using ui-v8 Python which has Kokoro installed
            worker_script = Path(__file__).parent.parent / "voice" / "kokoro_session_worker.py"
            python_exe = _get_ui_v8_python()
            
            self.process = subprocess.Popen(
                [python_exe, str(worker_script), "serve", "--socket", str(self.socket_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            
            # Wait for socket to become responsive
            start = asyncio.get_event_loop().time()
            while asyncio.get_event_loop().time() - start < timeout:
                if self._is_responsive():
                    return True
                await asyncio.sleep(0.05)
            
            # Failed to start
            self._kill()
            return False
    
    def _is_responsive(self) -> bool:
        """Quick check if worker is responsive."""
        import json
        import socket
        
        if not self.socket_path.exists():
            return False
        
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(0.5)
            sock.connect(str(self.socket_path))
            sock.send(json.dumps({"cmd": "prewarm"}).encode() + b"\n")
            response = json.loads(sock.recv(4096).decode())
            sock.close()
            return response.get("ok", False)
        except Exception:
            return False
    
    def _kill(self):
        """Kill worker process."""
        if self.process and self.process.poll() is None:
            try:
                self.process.terminate()
                self.process.wait(timeout=1.0)
            except:
                try:
                    self.process.kill()
                except:
                    pass
        self.process = None
        if self.socket_path.exists():
            try:
                self.socket_path.unlink()
            except:
                pass
    
    def stop(self):
        """Stop worker cleanly."""
        if self.process and self.process.poll() is None:
            # Try graceful shutdown via socket
            try:
                import json
                import socket
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.settimeout(1.0)
                sock.connect(str(self.socket_path))
                sock.send(json.dumps({"cmd": "quit"}).encode() + b"\n")
                sock.close()
                self.process.wait(timeout=2.0)
                return
            except:
                pass
        self._kill()


class StreamingVoicePipeline:
    """Voice pipeline that streams TTS as text arrives."""
    
    def __init__(self, voice: str = None):
        self.sample_rate = 22050  # Match Piper's sample rate
        self.channels = 1
        self.sample_width = 2
        self._cancelled = False
        self._kokoro_available = _detect_kokoro_availability()
        # Use consistent voice - default to af_bella (mature female)
        self.voice = voice or os.environ.get("LUCY_VOICE_KOKORO_VOICE", "af_bella")
        
        # Initialize worker manager
        socket_path = Path(__file__).parent.parent.parent / "tmp" / "run" / "kokoro_tts_worker.sock"
        self._worker = KokoroWorkerManager(socket_path)
        
    async def start(self) -> bool:
        """Initialize pipeline - start Kokoro worker."""
        return await self._worker.ensure_running()
        
    def stop(self):
        """Clean up - stop worker."""
        self._worker.stop()
        
    def cancel(self):
        self._cancelled = True
        
    async def stream_voice_interaction(
        self,
        audio_path: Path,
        on_transcription: Optional[callable] = None,
        on_response_chunk: Optional[callable] = None,
        on_response_ready: Optional[callable] = None,
    ) -> dict:
        from voice_tool import AudioBuffer
        
        result = {
            "success": False,
            "transcript": "",
            "response_text": "",
            "response_data": None,
            "error": "",
        }
        
        try:
            # Ensure worker is running
            if not await self._worker.ensure_running():
                print("Warning: Could not start Kokoro worker, using subprocess fallback")
            
            # Step 1: Transcribe
            print("Transcribing...")
            audio = AudioBuffer.from_file(audio_path)
            transcript = await self._transcribe_async(audio)
            result["transcript"] = transcript
            
            if on_transcription:
                on_transcription(transcript)
                
            if not transcript:
                result["error"] = "No speech detected"
                return result
                
            # Step 2: Get response from Lucy
            print(f"Query: {transcript}")
            print("Processing and streaming response...")
            
            response_data = await self._get_full_response(transcript)
            result["response_data"] = response_data
            
            if isinstance(response_data, dict):
                response_text = response_data.get("response_text", "")
                result["response_text"] = response_text
            else:
                response_text = str(response_data)
                result["response_text"] = response_text
            
            # Notify that full response is ready (before TTS starts)
            if on_response_ready:
                on_response_ready(response_text, response_data)
            
            # Step 3: Stream TTS
            if response_text:
                clean_text = self._clean_for_tts(response_text)
                await self._stream_tts_continuous(clean_text, on_response_chunk)
            
            result["success"] = True
            
        except Exception as e:
            result["error"] = str(e)
            print(f"Error: {e}")
            
        return result
    
    def _strip_html_for_tts(self, text: str) -> str:
        """Strip HTML tags from text for TTS synthesis."""
        import re
        
        if not text:
            return ""
        
        # Remove script and style elements
        text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
        
        # Replace <br>, <p> etc with newlines
        text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
        text = re.sub(r'</p>', '\n', text, flags=re.IGNORECASE)
        text = re.sub(r'<p[^>]*>', '', text, flags=re.IGNORECASE)
        
        # Replace <li> with bullet points
        text = re.sub(r'<li[^>]*>', '\n• ', text, flags=re.IGNORECASE)
        text = re.sub(r'</li>', '', text, flags=re.IGNORECASE)
        
        # Replace <a href="...">text</a> with just "text"
        text = re.sub(r'<a[^>]*href="([^"]*)"[^>]*>([^<]*)</a>', r'\2', text, flags=re.IGNORECASE)
        text = re.sub(r'<a[^>]*>([^<]*)</a>', r'\1', text, flags=re.IGNORECASE)
        
        # Remove all remaining HTML tags
        text = re.sub(r'<[^>]+>', '', text)
        
        # Decode common HTML entities
        text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
        text = text.replace('&quot;', '"').replace('&#39;', "'")
        text = text.replace('&nbsp;', ' ').replace('&#160;', ' ')
        text = text.replace('&#8211;', '–').replace('&#8212;', '—')
        text = text.replace('&#8216;', ''').replace('&#8217;', ''')
        text = text.replace('&#8220;', '"').replace('&#8221;', '"')
        
        # Normalize whitespace
        text = re.sub(r'\n\s*\n', '\n\n', text)
        text = re.sub(r'[ \t]+', ' ', text)
        
        return text.strip()

    def _clean_for_tts(self, text: str) -> str:
        """Clean text for TTS - strip HTML, news first, sources at the end."""
        import re
        
        # Strip HTML tags first
        text = self._strip_html_for_tts(text)
        
        # Remove common filler phrases at the start
        filler_patterns = [
            r'^(?:According to|Based on|From what I can see|It appears that)\s+',
            r'^(?:I found that|I see that|It seems)\s+',
        ]
        
        cleaned = text
        for pattern in filler_patterns:
            cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
        
        # Handle evidence source catalogs
        if 'From current sources:' in cleaned or 'Latest items extracted' in cleaned:
            lines = cleaned.split('\n')
            news_items = []
            sources = []
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                # Skip header/metadata lines
                if line.startswith('From current sources:'):
                    continue
                if line.startswith('Latest items extracted'):
                    continue
                if line.startswith('Key items:'):
                    continue
                if line.startswith('Conflicts/uncertainty:'):
                    continue
                if 'None assessed' in line and len(line) < 50:
                    continue
                
                # Extract news from bullet points
                if line.startswith('- ['):
                    match = re.match(r'- \[([^\]]+)\]\s*(?:\([^)]+\))?:?\s*(.+)', line)
                    if match:
                        source = match.group(1)
                        content = match.group(2)
                        content = re.sub(r'\s+', ' ', content).strip()
                        if content:
                            news_items.append(content)
                            if source not in sources:
                                sources.append(source)
                elif line.startswith('• '):
                    content = line[2:].strip()
                    if content:
                        news_items.append(content)
                elif line.startswith('Sources:') or line.startswith('Source:'):
                    # Skip source lines - extract domain for tracking but don't speak it
                    if line.startswith('Source: '):
                        domain = line[8:].strip()
                        if domain and domain not in sources:
                            sources.append(domain)
                    continue
                elif line.startswith('- ') and '.' not in line:
                    domain = line[2:].strip()
                    if domain and ' ' not in domain and domain not in sources:
                        sources.append(domain)
                else:
                    if len(line) > 10 and not line.startswith('-'):
                        news_items.append(line)
            
            result_parts = news_items
            # Sources intentionally omitted from TTS - only show in display text
            # if sources:
            #     result_parts.append(f"Sources: {', '.join(sources)}")
            
            cleaned = '. '.join(result_parts)
        
        # Remove evidence disabled messages
        cleaned = re.sub(r'Evidence disabled by operator control\.?\s*', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'Enable evidence to allow evidence routes\.?\s*', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'Best-effort recovery \(not source-backed answer\):\s*', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'From this unverified background,\s*', '', cleaned, flags=re.IGNORECASE)
        
        return cleaned.strip()
    
    async def _transcribe_async(self, audio) -> str:
        from voice_tool import VoicePipeline
        pipeline = VoicePipeline()
        return await pipeline.transcribe(audio)
    
    async def _get_full_response(self, query: str) -> dict:
        """Get response from Lucy using Python-native router."""
        from router_py.classify import classify_intent, select_route
        from router_py.execution_engine import ExecutionEngine
        from router_py.policy import normalize_augmentation_policy
        from router_py.main import ensure_control_env
        
        
        # Ensure control environment is loaded from state file
        ensure_control_env()
        
        # Longer timeout for voice - needs time for TTS + playback
        # News digests can take 2-3 minutes to speak completely
        engine = ExecutionEngine(config={
            "timeout": 300,  # 5 minutes for voice
            "use_sqlite_state": True,
        })
        
        try:
            classification = classify_intent(query, surface="voice")
            policy = normalize_augmentation_policy(
                os.environ.get("LUCY_AUGMENTATION_POLICY", "fallback_only")
            )
            decision = select_route(classification, policy=policy)
            
            # Map mode setting to forced_mode for execution engine
            mode = os.environ.get("LUCY_MODE", "auto").lower()
            forced_mode_map = {
                "auto": "AUTO",
                "online": "FORCED_ONLINE",
                "offline": "FORCED_OFFLINE",
            }
            forced_mode = forced_mode_map.get(mode, "AUTO")
            
            context = {
                "question": query,
                "output_mode": "DETAIL",
                "forced_mode": forced_mode,
            }
            result = engine.execute(
                intent=classification,
                route=decision,
                context=context,
                use_python_path=True,
            )
            
            # Persist chat memory turn if memory is enabled
            session_mem = os.environ.get("LUCY_SESSION_MEMORY", "NOT_SET")
            if os.environ.get("LUCY_SESSION_MEMORY") == "1" and result.response_text:
                try:
                    from router_py.execution_engine import DEFAULT_CHAT_MEMORY_FILE
                    # Check both runtime and standard env vars for memory file path
                    mem_file = os.environ.get("LUCY_RUNTIME_CHAT_MEMORY_FILE", "").strip()
                    if not mem_file:
                        mem_file = os.environ.get("LUCY_CHAT_MEMORY_FILE", "").strip()
                    if not mem_file:
                        mem_file = DEFAULT_CHAT_MEMORY_FILE
                    mem_path = Path(mem_file).expanduser()
                    mem_path.parent.mkdir(parents=True, exist_ok=True)
                    
                    # Format assistant text (clean up markers, truncate)
                    assistant_text = (
                        result.response_text.replace("BEGIN_VALIDATED", " ")
                        .replace("END_VALIDATED", " ")
                        .replace("\r", " ")
                        .replace("\n", " ")
                    )
                    assistant_text = re.sub(r"\s+", " ", assistant_text).strip()
                    if len(assistant_text) > 500:
                        assistant_text = assistant_text[:500]
                    
                    # Read existing content
                    existing = ""
                    try:
                        existing = mem_path.read_text(encoding="utf-8")
                    except FileNotFoundError:
                        pass
                    
                    # Build new block and append
                    block = f"User: {query.strip()}\nAssistant: {assistant_text}\n\n"
                    blocks = [item.strip() for item in re.split(r"\n\s*\n", existing) if item.strip()]
                    blocks.append(block.strip())
                    
                    # Keep only last 6 turns
                    max_turns = 6
                    trimmed = "\n\n".join(blocks[-max_turns:]).strip()
                    if trimmed:
                        trimmed += "\n\n"
                    
                    mem_path.write_text(trimmed, encoding="utf-8")
                except Exception as e:
                    pass
            
            return {
                "status": "completed" if result.status == "completed" else result.status,
                "response_text": result.response_text or "",
                "route": result.route,
                "provider": result.provider,
                "outcome_code": result.outcome_code,
                "execution_time_ms": result.execution_time_ms,
            }
        finally:
            engine.close()
    
    async def _stream_tts_continuous(
        self,
        response_text: str,
        on_response_chunk: Optional[callable] = None,
    ):
        """Stream TTS - simple phrase-by-phrase approach."""
        import re
        import struct
        import logging
        
        logger = logging.getLogger("streaming_voice")
        logger.info(f"[_stream_tts_continuous] Starting TTS for {len(response_text)} chars")
        print(f"[TTS Debug] Input text length: {len(response_text)} chars, {response_text.count('.')} sentences")
        
        # Split into phrases
        phrases = re.split(r'(?<=[.!?])\s+|(?<=,)\s+', response_text)
        phrases = [p for p in phrases if p.strip()]
        
        # Further split very long phrases (>400 chars) to avoid timeout/failure
        MAX_PHRASE_LEN = 400
        final_phrases = []
        for phrase in phrases:
            if len(phrase) <= MAX_PHRASE_LEN:
                final_phrases.append(phrase)
            else:
                # Split long phrase by sentence boundaries
                sentences = re.split(r'(?<=[.!?])\s+', phrase)
                current_chunk = ""
                for sentence in sentences:
                    if len(current_chunk) + len(sentence) <= MAX_PHRASE_LEN:
                        current_chunk += sentence + " "
                    else:
                        if current_chunk.strip():
                            final_phrases.append(current_chunk.strip())
                        current_chunk = sentence + " "
                if current_chunk.strip():
                    final_phrases.append(current_chunk.strip())
        
        phrases = final_phrases
        print(f"[TTS Debug] Split into {len(phrases)} phrases (max {MAX_PHRASE_LEN} chars each)")
        
        if not phrases:
            if on_response_chunk:
                on_response_chunk(response_text)
            return
        
        # Synthesize FIRST chunk before starting playback
        first_chunk_pcm = await self._synthesize_to_pcm(phrases[0])
        if not first_chunk_pcm:
            phrases = phrases[1:]
            if phrases:
                first_chunk_pcm = await self._synthesize_to_pcm(phrases[0])
        
        if not first_chunk_pcm and not phrases:
            if on_response_chunk:
                on_response_chunk(response_text)
            return
        
        # Add prepad silence (120ms)
        PREPAD_MS = 120
        silence_samples = int(self.sample_rate * (PREPAD_MS / 1000.0))
        prepad_silence = struct.pack(f'<{silence_samples}h', *([0] * silence_samples))
        
        # Start aplay with larger buffer for smoother playback
        aplay_proc = await asyncio.create_subprocess_exec(
            "aplay", "-t", "raw", "-f", "S16_LE", "-r", str(self.sample_rate), 
            "-c", str(self.channels), "-q", "-",
            "--buffer-size=65536",  # Larger buffer to prevent underrun
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        
        # Setup VU meter level tracking with time-based level map
        # Pre-calculate all audio levels and their timestamps for accurate VU meter
        levels_file = _get_audio_levels_file()
        level_running = [True]
        playback_start_time = [0.0]  # Will be set when first audio is written
        level_map = []  # List of (timestamp_ms, level) tuples
        
        def level_writer():
            """Background thread: write current level based on playback time."""
            write_count = 0
            
            # Wait for playback to start
            while level_running[0] and playback_start_time[0] == 0.0:
                time.sleep(0.01)
            
            if not level_running[0]:
                return
            
            last_level = 0
            while level_running[0]:
                try:
                    # Calculate current playback position
                    elapsed_ms = (time.time() - playback_start_time[0]) * 1000
                    
                    # Find the level for current playback position
                    # Use the last level where timestamp_ms <= elapsed_ms
                    current_level = last_level
                    for timestamp_ms, level in level_map:
                        if elapsed_ms >= timestamp_ms:
                            current_level = level
                        else:
                            break
                    last_level = current_level
                    
                    _write_output_level(current_level, levels_file)
                    write_count += 1
                except Exception:
                    pass
                time.sleep(0.03)  # 30ms = ~33fps
            
            # Final write with zero level
            try:
                _write_output_level(0, levels_file)
            except Exception:
                pass
        
        # Start level writer thread
        level_thread = threading.Thread(target=level_writer, daemon=True)
        level_thread.start()
        
        try:
            # Build detailed level map with 30ms chunks for accurate VU meter
            # Each entry: (timestamp_ms, level)
            current_time_ms = 0
            
            # Prepad silence: 120ms at level 0
            level_map.append((current_time_ms, 0))
            current_time_ms += PREPAD_MS
            
            # Send prepad silence first
            aplay_proc.stdin.write(prepad_silence)
            await aplay_proc.stdin.drain()
            
            def add_pcm_to_level_map(pcm_data: bytes, base_time_ms: float) -> float:
                """Analyze PCM into 30ms chunks and add to level map. Returns new time."""
                time_ms = base_time_ms
                levels = _analyze_pcm_levels(pcm_data, self.sample_rate, chunk_duration_ms=30.0)
                for level in levels:
                    level_map.append((time_ms, level))
                    time_ms += 30.0  # 30ms per chunk
                return time_ms
            
            # Now send the first chunk
            if first_chunk_pcm:
                # Analyze into detailed chunks
                current_time_ms = add_pcm_to_level_map(first_chunk_pcm, current_time_ms)
                
                # Mark playback start time when first real audio is sent
                if playback_start_time[0] == 0.0:
                    playback_start_time[0] = time.time()
                
                aplay_proc.stdin.write(first_chunk_pcm)
                await aplay_proc.stdin.drain()
                
                if on_response_chunk:
                    on_response_chunk(phrases[0] + " ")
            
            # Process remaining phrases
            revealed = phrases[0] + " " if first_chunk_pcm else ""
            phrases_processed = 1 if first_chunk_pcm else 0
            phrases_failed = 0
            
            for i, phrase in enumerate(phrases[1:], 1):
                if self._cancelled:
                    print(f"[TTS Debug] Cancelled after {phrases_processed} phrases")
                    break
                
                audio_data = await self._synthesize_to_pcm(phrase)
                
                if audio_data:
                    # Analyze into detailed chunks
                    current_time_ms = add_pcm_to_level_map(audio_data, current_time_ms)
                    
                    aplay_proc.stdin.write(audio_data)
                    await aplay_proc.stdin.drain()
                    phrases_processed += 1
                else:
                    phrases_failed += 1
                    print(f"[TTS Debug] Phrase {i+1} failed ({len(phrase)} chars): {phrase[:80]}...")
                
                if on_response_chunk:
                    revealed += phrase + " "
                    on_response_chunk(revealed)
            
            print(f"[TTS Debug] Processed {phrases_processed}/{len(phrases)} phrases, {phrases_failed} failed")
            
            # Add trailing silence to ensure last audio plays (2000ms = 2 seconds)
            # This is critical - aplay needs enough silence to flush its buffer
            TRAILING_MS = 2000
            trailing_samples = int(self.sample_rate * (TRAILING_MS / 1000.0))
            trailing_silence = struct.pack(f'<{trailing_samples}h', *([0] * trailing_samples))
            # Mark level 0 for trailing silence period
            level_map.append((current_time_ms, 0))
            aplay_proc.stdin.write(trailing_silence)
            await aplay_proc.stdin.drain()
            
            # Close stdin to signal EOF - aplay will finish when buffer is empty
            await aplay_proc.stdin.drain()
            aplay_proc.stdin.close()
            
            # Wait for aplay to actually finish playing all audio
            # This is more reliable than fixed sleep - aplay exits only after playback
            print(f"[TTS Debug] Waiting for playback to complete...")
            try:
                # Longer timeout for long content (30s instead of 10s)
                await asyncio.wait_for(aplay_proc.wait(), timeout=30.0)
                print(f"[TTS Debug] Playback complete")
            except asyncio.TimeoutError:
                print("[TTS Debug] aplay wait timeout, killing process")
                aplay_proc.kill()
                await aplay_proc.wait()
        finally:
            # Stop level writer
            level_running[0] = False
            level_thread.join(timeout=0.5)
    
    async def _synthesize_to_pcm(self, text: str) -> bytes:
        """Synthesize using Kokoro worker socket or subprocess fallback."""
        if not text.strip():
            return b""
        
        # Try Kokoro worker first (managed by this pipeline) - fast path
        pcm_data = await self._synthesize_via_worker(text)
        if pcm_data:
            return pcm_data
        
        # Fallback to subprocess
        return await self._synthesize_subprocess_to_pcm(text)
    
    async def _synthesize_via_worker(self, text: str) -> bytes:
        """Use Kokoro worker socket for fast synthesis."""
        import socket
        import json
        import tempfile
        import wave
        import numpy as np
        
        # Check phrase length - if too long, may cause issues
        if len(text) > 500:
            print(f"[TTS Debug] Warning: Long phrase ({len(text)} chars), may timeout")
        
        if not self._worker.socket_path.exists():
            print(f"[TTS Debug] Worker socket not found, skipping synthesis")
            return b""
        
        try:
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
                tmp_path = tmp.name
            
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            # Increase timeout for long phrases
            timeout = 30.0 if len(text) > 300 else 10.0
            sock.settimeout(timeout)
            sock.connect(str(self._worker.socket_path))
            
            request = {
                'cmd': 'synthesize',
                'engine': 'kokoro',
                'text': text,
                'voice': self.voice,
                'output_dir': str(Path(tmp_path).parent)
            }
            
            sock.send(json.dumps(request).encode() + b'\n')
            response_data = sock.recv(4096).decode()
            sock.close()
            
            response = json.loads(response_data)
            
            if not response.get('ok'):
                error_msg = response.get('error', 'unknown error')
                print(f"[TTS Debug] Worker error: {error_msg}")
                return b""
            
            wav_path = response.get('wav_path')
            if not wav_path or not Path(wav_path).exists():
                print(f"[TTS Debug] No WAV file produced")
                return b""
            
            with wave.open(wav_path, 'rb') as wav:
                source_rate = wav.getframerate()
                pcm_data = wav.readframes(wav.getnframes())
            
            try:
                Path(wav_path).unlink()
            except:
                pass
            
            # Resample if needed (Kokoro outputs 24kHz, aplay expects 22050 Hz)
            if source_rate != self.sample_rate:
                try:
                    # Convert bytes to numpy array
                    audio = np.frombuffer(pcm_data, dtype=np.int16).astype(np.float32) / 32767.0
                    
                    # Simple linear interpolation resampling
                    ratio = self.sample_rate / source_rate
                    new_length = int(len(audio) * ratio)
                    old_indices = np.arange(len(audio))
                    new_indices = np.linspace(0, len(audio) - 1, new_length)
                    audio_resampled = np.interp(new_indices, old_indices, audio)
                    
                    # Convert back to int16 bytes
                    pcm_data = (audio_resampled * 32767).astype(np.int16).tobytes()
                except Exception as e:
                    print(f"[TTS Debug] Resampling error: {e}")
                    # Return original data if resampling fails
            
            return pcm_data
            
        except socket.timeout:
            print(f"[TTS Debug] Timeout synthesizing phrase ({len(text)} chars)")
            return b""
        except Exception as e:
            print(f"[TTS Debug] Worker error: {e}")
            return b""
    
    async def _synthesize_subprocess_to_pcm(self, text: str) -> bytes:
        """Fallback subprocess synthesis."""
        helper_path = Path(__file__).parent / "streaming_tts_helper.py"
        voice_python = _get_ui_v8_python()
        
        pcm_data = b""
        
        try:
            proc = await asyncio.create_subprocess_exec(
                voice_python, str(helper_path), text,
                "--voice", self.voice, "--speed", "1.0",
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            
            while True:
                chunk = await proc.stdout.read(4096)
                if not chunk:
                    break
                pcm_data += chunk
                
                if self._cancelled:
                    proc.kill()
                    break
            
            await proc.wait()
        except Exception as e:
            print(f"TTS subprocess error: {e}")
        
        return pcm_data


async def main():
    if len(sys.argv) < 2:
        print("Usage: streaming_voice.py <audio.wav>")
        return
        
    audio_path = Path(sys.argv[1])
    if not audio_path.exists():
        print(f"Audio file not found: {audio_path}")
        return
    
    pipeline = StreamingVoicePipeline()
    
    def on_transcript(text):
        print(f"Transcript: {text}")
    
    def on_chunk(chunk):
        print(chunk, end='', flush=True)
    
    result = await pipeline.stream_voice_interaction(
        audio_path, on_transcription=on_transcript, on_response_chunk=on_chunk
    )
    
    print(f"\n\nSuccess: {result['success']}")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
