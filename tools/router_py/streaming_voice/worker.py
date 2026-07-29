"""Kokoro availability / UI path helpers and worker subprocess lifecycle."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Optional


def _get_ui_v10_python() -> str:
    """Get path to ui-v10 Python which has Kokoro installed."""
    root = Path(__file__).resolve().parent.parent.parent.parent
    return str(root / "ui-v10" / ".venv" / "bin" / "python3")


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

            # Start worker using ui-v10 Python which has Kokoro installed
            worker_script = Path(__file__).resolve().parent.parent.parent / "voice" / "kokoro_session_worker.py"
            python_exe = _get_ui_v10_python()

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
