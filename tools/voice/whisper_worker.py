#!/usr/bin/env python3
"""Persistent whisper-server worker manager for Local Lucy v10.

Mirrors the Kokoro session worker pattern (PID file, health checks, stale cleanup)
but uses HTTP instead of a Unix domain socket.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

try:
    import requests

    _HAS_REQUESTS = True
except ImportError:
    requests = None  # type: ignore[assignment]
    _HAS_REQUESTS = False


class WhisperWorkerError(RuntimeError):
    """Raised when the persistent whisper worker fails."""

    pass


def _gpu_available() -> bool:
    """Detect whether a CUDA GPU is available for whisper.cpp."""
    # Respect explicit environment override
    env_gpu = os.environ.get("LUCY_VOICE_WHISPER_GPU", "").strip().lower()
    if env_gpu in ("1", "true", "yes", "on"):
        return True
    if env_gpu in ("0", "false", "no", "off"):
        return False
    # Auto-detect via pynvml when available
    try:
        import pynvml

        pynvml.nvmlInit()
        try:
            pynvml.nvmlDeviceGetHandleByIndex(0)
            return True
        finally:
            pynvml.nvmlShutdown()
    except Exception:
        pass

    # Fallback: parse /proc/driver/nvidia/gpus/*/information for a model name
    try:
        for info_path in Path("/proc/driver/nvidia/gpus").glob("*/information"):
            text = info_path.read_text(encoding="utf-8", errors="replace")
            if "model:" in text.lower():
                return True
    except Exception:
        pass
    return False


WHISPER_SERVER_DEFAULT_PORT = 18181
WHISPER_SERVER_PORT_ENV = "LUCY_WHISPER_SERVER_PORT"
WHISPER_SERVER_DISABLE_ENV = "LUCY_WHISPER_SERVER_DISABLE"


def _resolve_root() -> Path:
    env_root = os.environ.get("LUCY_RUNTIME_AUTHORITY_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


def resolve_whisper_server_binary() -> Path:
    return (
        _resolve_root() / "runtime" / "voice" / "whisper.cpp" / "build" / "bin" / "whisper-server"
    )


def resolve_whisper_worker_pid_file() -> Path:
    return _resolve_root() / "tmp" / "run" / "whisper_worker.pid"


def resolve_whisper_worker_log_file() -> Path:
    return _resolve_root() / "tmp" / "logs" / "whisper_worker.log"


def resolve_whisper_worker_port() -> int:
    raw = os.environ.get(WHISPER_SERVER_PORT_ENV, str(WHISPER_SERVER_DEFAULT_PORT))
    try:
        return int(raw)
    except ValueError:
        return WHISPER_SERVER_DEFAULT_PORT


def _remove_stale_whisper_worker_files() -> None:
    for path in (resolve_whisper_worker_pid_file(),):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass


def _is_process_running(pid: int | None) -> bool:
    if pid is None or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _read_pid_file(path: Path) -> int | None:
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _health_check(port: int, timeout: float = 2.0) -> bool:
    if not _HAS_REQUESTS:
        return False
    try:
        resp = requests.get(f"http://127.0.0.1:{port}/health", timeout=timeout)
        return resp.status_code == 200
    except Exception:
        return False


def resolve_whisper_language(model_path: Path | str | None = None) -> str:
    """Return the whisper language flag for the active model/configuration.

    Order of precedence:
      1. LUCY_VOICE_WHISPER_LANGUAGE environment variable
      2. 'en' for English-only *.en.bin models
      3. 'auto' for multilingual models
    """
    explicit = os.environ.get("LUCY_VOICE_WHISPER_LANGUAGE", "").strip().lower()
    if explicit and explicit not in {"none", "default"}:
        return explicit
    path = str(model_path or "")
    if ".en.bin" in path:
        return "en"
    return "auto"


def ensure_whisper_worker(
    model_path: Path | str,
    *,
    use_gpu: bool | None = None,
    port: int | None = None,
    language: str | None = None,
) -> int | None:
    """Start the whisper-server worker if not already running.

    Returns the port number on success, or None if the worker could not be
    started (or if disabled via LUCY_WHISPER_SERVER_DISABLE=1).

    GPU usage is auto-detected via nvidia-smi unless explicitly disabled
    via LUCY_VOICE_WHISPER_GPU=0 or the use_gpu parameter.

    Language defaults to the value returned by resolve_whisper_language(model_path).
    """
    if use_gpu is None:
        use_gpu = _gpu_available()
    if os.environ.get(WHISPER_SERVER_DISABLE_ENV) == "1":
        return None

    if port is None:
        port = resolve_whisper_worker_port()

    binary = resolve_whisper_server_binary()
    if not binary.exists():
        return None

    pid_file = resolve_whisper_worker_pid_file()
    worker_pid = _read_pid_file(pid_file)

    if worker_pid is not None and _is_process_running(worker_pid) and _health_check(port):
        return port

    _remove_stale_whisper_worker_files()
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    resolve_whisper_worker_log_file().parent.mkdir(parents=True, exist_ok=True)

    whisper_language = language if language else resolve_whisper_language(model_path)
    command = [
        str(binary),
        "--model",
        str(model_path),
        "--port",
        str(port),
        "--host",
        "127.0.0.1",
        "--language",
        whisper_language,
        "--no-timestamps",
        "--beam-size",
        "1",
        "--best-of",
        "1",
        "--threads",
        "4",
    ]
    if not use_gpu:
        command.append("--no-gpu")

    log_handle = resolve_whisper_worker_log_file().open("a", encoding="utf-8")
    try:
        proc = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=log_handle,
            shell=False,
            start_new_session=True,
            env=os.environ.copy(),
        )
    finally:
        log_handle.close()

    pid_file.write_text(f"{proc.pid}\n", encoding="utf-8")

    for _ in range(60):
        if _health_check(port):
            return port
        time.sleep(0.05)

    # Health check timed out — kill the orphan process to avoid port conflicts
    # and resource leaks.
    try:
        proc.terminate()
        for _ in range(20):
            if proc.poll() is not None:
                break
            time.sleep(0.05)
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=1.0)
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def _find_whisper_server_pids() -> list[int]:
    """Find any whisper-server processes that match our binary path.

    Used as a fallback when the PID file is missing or stale, so a resident
    worker does not leak across Local Lucy restarts.
    """
    binary = resolve_whisper_server_binary()
    pids: list[int] = []
    try:
        for proc_dir in Path("/proc").glob("[0-9]*"):
            try:
                pid = int(proc_dir.name)
            except ValueError:
                continue
            try:
                cmdline = (proc_dir / "cmdline").read_text(errors="replace")
            except (OSError, PermissionError):
                continue
            # cmdline uses NUL separators; look for the binary path or name.
            if str(binary) in cmdline or "whisper-server" in cmdline:
                pids.append(pid)
    except Exception:
        pass
    return pids


def _kill_pid(pid: int) -> None:
    """Send SIGTERM, then SIGKILL if necessary."""
    if pid <= 0 or not _is_process_running(pid):
        return
    try:
        os.kill(pid, signal.SIGTERM)
        for _ in range(20):
            if not _is_process_running(pid):
                return
            time.sleep(0.05)
        if _is_process_running(pid):
            os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


def stop_whisper_worker() -> None:
    """Terminate the whisper-server worker if it is running."""
    pid_file = resolve_whisper_worker_pid_file()
    worker_pid = _read_pid_file(pid_file)
    if worker_pid is not None:
        _kill_pid(worker_pid)

    # Fallback: any other whisper-server processes spawned from this binary path.
    for pid in _find_whisper_server_pids():
        if pid != worker_pid:
            _kill_pid(pid)

    _remove_stale_whisper_worker_files()


def transcribe_with_worker(
    wav_path: Path | str,
    port: int,
    *,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Send a WAV file to the persistent whisper worker and return the transcript.

    Returns a dict with keys: ``text``, ``backend``, ``fallback_used``.

    Raises:
        WhisperWorkerError: on any network, HTTP, or parsing failure.
    """
    if not _HAS_REQUESTS:
        raise WhisperWorkerError("requests library not available")

    try:
        with open(wav_path, "rb") as f:
            resp = requests.post(
                f"http://127.0.0.1:{port}/inference",
                files={"file": f},
                timeout=(2.0, timeout),
            )
    except requests.RequestException as exc:
        raise WhisperWorkerError(f"whisper worker request failed: {exc}") from exc
    except OSError as exc:
        raise WhisperWorkerError(f"whisper worker unable to read audio file: {exc}") from exc

    if resp.status_code != 200:
        raise WhisperWorkerError(
            f"whisper worker returned status {resp.status_code}: {resp.text[:200]}"
        )

    try:
        payload = resp.json()
    except json.JSONDecodeError as exc:
        raise WhisperWorkerError(f"whisper worker returned invalid JSON: {exc}") from exc

    text = payload.get("text") or ""
    return {
        "text": text.strip(),
        "backend": "gpu",
        "fallback_used": False,
        "fallback_reason": "",
    }


if __name__ == "__main__":
    # Minimal CLI: called by START_LUCY.sh to stop any stale resident worker.
    stop_whisper_worker()
