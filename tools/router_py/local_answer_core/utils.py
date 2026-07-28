#!/usr/bin/env python3
"""Local answer utility helpers."""

from __future__ import annotations

import logging
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any


class _OllamaWarmupThread(threading.Thread):
    """Daemon thread that pings Ollama periodically to keep the model loaded.

    Uses a lightweight generate request (empty prompt, num_predict=0) so the
    model stays hot in VRAM without wasting compute or tokens.
    """

    def __init__(
        self,
        interval_s: int,
        model: str,
        api_url: str,
        keep_alive: str,
    ):
        super().__init__(daemon=True, name="ollama-warmup")
        self.interval_s = interval_s
        self.model = model
        self.api_url = api_url
        self.keep_alive = keep_alive
        self._stop_event = threading.Event()

    def run(self) -> None:
        while not self._stop_event.is_set():
            # Wait for the interval, but wake early if stopped
            if self._stop_event.wait(self.interval_s):
                break
            # If the authoritative state file now points to a different model,
            # exit without pinging so the old model is not re-loaded.
            active_model = _get_active_model_from_state() or self.model
            if active_model != self.model:
                break
            if LocalAnswer._warmup_thread is not None and LocalAnswer._warmup_thread is not self:
                break
            self._ping()

    def _ping(self) -> None:
        # Abort if the authoritative state file points to a different model or
        # a newer warmup thread has replaced this one.
        active_model = _get_active_model_from_state() or self.model
        if (
            active_model != self.model
            or (LocalAnswer._warmup_thread is not None and LocalAnswer._warmup_thread is not self)
            or self._stop_event.is_set()
        ):
            return
        body = {
            "model": self.model,
            "prompt": "",
            "stream": False,
            "keep_alive": self.keep_alive,
            "options": {"num_predict": 0},
        }
        try:
            req = urllib.request.Request(
                self.api_url,
                data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30.0) as resp:
                resp.read()
        except Exception:
            pass  # Silently fail — Ollama may not be running yet

    def stop(self) -> None:
        self._stop_event.set()


def get_gpu_free_vram_mb() -> int | None:
    """Return free NVIDIA VRAM in MB, or None if not detectable."""
    try:
        import pynvml  # type: ignore

        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        info = pynvml.nvmlDeviceGetMemoryInfo(handle)
        return int(info.free // (1024 * 1024))
    except Exception:
        pass
    try:
        out = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.free",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if out.returncode == 0:
            return int(out.stdout.strip().split("\n")[0].strip())
    except Exception:
        pass
    return None
