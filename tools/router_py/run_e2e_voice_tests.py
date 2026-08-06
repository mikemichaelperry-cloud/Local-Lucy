#!/usr/bin/env python3
"""End-to-end voice tests for Local Lucy v11.

Generates spoken input WAVs with Kokoro, feeds them through the voice pipeline,
plays Lucy's spoken response through aplay, and reports timings.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VOICE_PYTHON = ROOT / "ui-v10" / ".venv" / "bin" / "python3"
TTS_ADAPTER = ROOT / "tools" / "voice" / "tts_adapter.py"
KOKORO_WORKER_SCRIPT = ROOT / "tools" / "voice" / "kokoro_session_worker.py"
WHISPER_WORKER = ROOT / "tools" / "voice" / "whisper_worker.py"
SOCKET_PATH = ROOT / "tmp" / "run" / "kokoro_tts_worker.sock"
OUT_DIR = Path.home() / "Desktop" / "lucy_v11_e2e_voice_tests"

# The bundled whisper model is ggml-base.en.bin, not ggml-base.bin.
os.environ.setdefault("LUCY_VOICE_MODEL", "base.en")

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "router_py"))


def ensure_kokoro_worker() -> bool:
    """Start the Kokoro worker if it is not already listening."""
    if SOCKET_PATH.exists():
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(1.0)
            sock.connect(str(SOCKET_PATH))
            sock.send(json.dumps({"cmd": "prewarm"}).encode() + b"\n")
            resp = json.loads(sock.recv(4096).decode())
            sock.close()
            if resp.get("ok"):
                return True
        except Exception:
            pass
        try:
            SOCKET_PATH.unlink()
        except Exception:
            pass

    log = ROOT / "tmp" / "logs" / "kokoro_tts_worker.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        [str(VOICE_PYTHON), str(KOKORO_WORKER_SCRIPT), "serve", "--socket", str(SOCKET_PATH)],
        stdout=subprocess.DEVNULL,
        stderr=log.open("a"),
    )
    # Wait for socket
    deadline = time.time() + 15.0
    while time.time() < deadline:
        if SOCKET_PATH.exists():
            try:
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.settimeout(1.0)
                sock.connect(str(SOCKET_PATH))
                sock.send(json.dumps({"cmd": "prewarm"}).encode() + b"\n")
                resp = json.loads(sock.recv(4096).decode())
                sock.close()
                if resp.get("ok"):
                    return True
            except Exception:
                pass
        time.sleep(0.1)
    proc.terminate()
    return False


def ensure_whisper_worker() -> bool:
    """Start the persistent Whisper worker if it is not running."""
    sys.path.insert(0, str(ROOT / "tools" / "voice"))
    import whisper_worker

    model_path = ROOT / "runtime" / "voice" / "models" / "ggml-base.en.bin"
    port = whisper_worker.ensure_whisper_worker(str(model_path))
    return port is not None


def synthesize_input(text: str, output_path: Path) -> bool:
    """Use the Kokoro worker to create a spoken query WAV."""
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(15.0)
        sock.connect(str(SOCKET_PATH))
        sock.send(json.dumps({"cmd": "synthesize", "engine": "kokoro", "text": text, "voice": "af_bella", "output_dir": str(output_path.parent)}).encode() + b"\n")
        resp = json.loads(sock.recv(4096).decode())
        sock.close()
        if not resp.get("ok"):
            return False
        src = Path(resp["wav_path"])
        if not src.exists():
            return False
        src.rename(output_path)
        return True
    except Exception as exc:
        print(f"[input synth error] {exc}")
        return False


async def run_test(query_text: str, index: int, pipelines: list) -> dict:
    """Run one E2E voice test and return timings/result."""
    from router_py.streaming_voice.pipeline import StreamingVoicePipeline

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    input_wav = OUT_DIR / f"input_{index:02d}_{_safe(query_text)}.wav"
    output_wav = OUT_DIR / f"response_{index:02d}_{_safe(query_text)}.wav"

    print(f"\n=== Test {index}: {query_text!r} ===")

    t0 = time.time()
    if not synthesize_input(query_text, input_wav):
        return {"error": "input synthesis failed"}
    input_synth_ms = int((time.time() - t0) * 1000)
    print(f"Input WAV: {input_wav} ({input_synth_ms} ms)")

    if not ensure_kokoro_worker():
        return {"error": "Kokoro worker not available"}

    pipeline = StreamingVoicePipeline()
    pipelines.append(pipeline)
    if not await pipeline.start():
        return {"error": "failed to start streaming voice pipeline"}

    response_chunks: list[str] = []

    def on_transcription(transcript: str):
        print(f"[transcribed] {transcript!r}")

    def on_response_chunk(revealed: str):
        response_chunks.append(revealed)
        print(f"[spoken chunk] {revealed[:120]}...")

    def on_response_ready(text: str, data):
        print(f"[response ready] {text[:120]}...")

    t0 = time.time()
    result = await pipeline.stream_voice_interaction(
        audio_path=input_wav,
        on_transcription=on_transcription,
        on_response_chunk=on_response_chunk,
        on_response_ready=on_response_ready,
    )
    total_ms = int((time.time() - t0) * 1000)

    # The streaming pipeline plays audio via aplay; we also want a saved WAV copy.
    # Re-synthesize the full response text for the desktop copy.
    response_text = result.get("response_text", "")
    if response_text:
        saved = await _save_response_wav(response_text, output_wav)
        if saved:
            print(f"Response WAV saved: {output_wav}")

    # Play the saved response explicitly so the user hears it.
    if output_wav.exists():
        try:
            play_proc = await asyncio.create_subprocess_exec(
                "aplay", "-q", str(output_wav),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(play_proc.communicate(), timeout=60.0)
            if play_proc.returncode != 0:
                print(f"aplay stderr: {stderr.decode(errors='replace')[:200]}")
        except Exception as exc:
            print(f"aplay error: {exc}")

    return {
        "success": result.get("success", False),
        "query": query_text,
        "transcript": result.get("transcript", ""),
        "response_text": response_text,
        "total_ms": total_ms,
        "input_wav": str(input_wav),
        "output_wav": str(output_wav),
        "error": result.get("error", ""),
    }


async def _save_response_wav(text: str, output_path: Path) -> bool:
    """Synthesize full response text to a WAV file using the worker."""
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(30.0)
        sock.connect(str(SOCKET_PATH))
        sock.send(json.dumps({"cmd": "synthesize", "engine": "kokoro", "text": text, "voice": "af_bella", "output_dir": str(output_path.parent)}).encode() + b"\n")
        resp = json.loads(sock.recv(4096).decode())
        sock.close()
        if not resp.get("ok"):
            return False
        src = Path(resp["wav_path"])
        if not src.exists():
            return False
        src.rename(output_path)
        return True
    except Exception as exc:
        print(f"[response save error] {exc}")
        return False


def _safe(text: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in text[:40]).rstrip("_")


async def main():
    if not ensure_kokoro_worker():
        print("ERROR: Could not start Kokoro worker")
        return 1
    if not ensure_whisper_worker():
        print("ERROR: Could not start Whisper worker")
        return 1

    queries = [
        "What is the capital of France?",
        "Tell me a short joke.",
        "What is Local Lucy?",
    ]

    pipelines: list[StreamingVoicePipeline] = []
    results = []
    for i, query in enumerate(queries, 1):
        try:
            result = await run_test(query, i, pipelines)
            results.append(result)
        except Exception as exc:
            print(f"Test {i} failed: {exc}")
            results.append({"error": str(exc)})
        # Small gap between utterances
        await asyncio.sleep(1.0)

    for pipeline in pipelines:
        try:
            pipeline.stop()
        except Exception:
            pass

    print("\n=== E2E Voice Test Summary ===")
    for r in results:
        if "error" in r and r["error"]:
            print(f"FAIL: {r.get('query','?')} — {r['error']}")
        else:
            print(f"OK:   {r.get('query','?')}")
            print(f"      transcript: {r.get('transcript','')!r}")
            print(f"      response:   {r.get('response_text','')[:200]!r}")
            print(f"      total_ms:   {r.get('total_ms',0)}")
            print(f"      output:     {r.get('output_wav','')}")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
