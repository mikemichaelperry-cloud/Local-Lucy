#!/usr/bin/env python3
"""Local Lucy v10 — Environment Validation Script

Run this on a fresh machine to verify all dependencies are present
before attempting to launch Local Lucy.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def _ok(msg: str) -> None:
    print(f"  \033[32m✓\033[0m {msg}")


def _fail(msg: str, fix: str = "") -> None:
    print(f"  \033[31m✗\033[0m {msg}")
    if fix:
        print(f"    → {fix}")


def _warn(msg: str, fix: str = "") -> None:
    print(f"  \033[33m!\033[0m {msg}")
    if fix:
        print(f"    → {fix}")


def check_python() -> bool:
    print("[1/8] Python version")
    version = sys.version_info
    if version >= (3, 10):
        _ok(f"Python {version.major}.{version.minor}.{version.micro}")
        return True
    _fail(f"Python {version.major}.{version.minor} — requires 3.10+",
          "Install Python 3.10 or newer")
    return False


def check_venv() -> bool:
    print("[2/8] Virtual environment")
    venv_python = Path("ui-v10/.venv/bin/python3")
    if venv_python.exists():
        _ok(f"venv found at {venv_python}")
        return True
    _warn("venv not found at ui-v10/.venv",
          "Run: make install   (or: python3 -m venv ui-v10/.venv)")
    return False


def check_ollama() -> bool:
    print("[3/8] Ollama daemon")
    ollama_bin = shutil.which("ollama")
    if not ollama_bin:
        _fail("ollama not found in PATH",
              "Install from https://ollama.com and start the service")
        return False

    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            _ok(f"ollama running ({ollama_bin})")
            return True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    _fail("ollama installed but daemon not responding",
          "Start ollama:  ollama serve")
    return False


def check_models() -> bool:
    print("[4/8] Required models")
    required = ["local-lucy-llama31"]
    recommended = ["local-lucy-fast", "local-lucy-mistral"]
    ok = True

    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        installed = [line.split()[0] for line in result.stdout.splitlines() if line.strip()]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        _fail("cannot query ollama for models")
        return False

    for model in required:
        if model in installed:
            _ok(f"model '{model}' installed")
        else:
            _fail(f"required model '{model}' not found",
                  f"Pull it:  ollama pull {model}")
            ok = False

    for model in recommended:
        if model in installed:
            _ok(f"optional model '{model}' installed")
        else:
            _warn(f"optional model '{model}' not found",
                  f"Pull it:  ollama pull {model}")

    return ok


def check_cuda() -> bool:
    print("[5/8] CUDA / GPU")
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().splitlines():
                name, mem = line.split(",")
                _ok(f"GPU: {name.strip()} ({mem.strip()})")
            return True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    _warn("CUDA / nvidia-smi not available",
          "GPU inference unavailable; CPU-only mode will be slower")
    return False


def check_pyside6() -> bool:
    print("[6/8] PySide6")
    try:
        import PySide6
        _ok(f"PySide6 {PySide6.__version__}")
        return True
    except ImportError:
        _fail("PySide6 not installed",
              "Run: make install")
        return False


def check_dependencies() -> bool:
    print("[7/8] Core Python dependencies")
    deps = [
        ("torch", "PyTorch"),
        ("transformers", "Hugging Face transformers"),
        ("sentence_transformers", "sentence-transformers"),
        ("aiohttp", "aiohttp"),
        ("kokoro", "Kokoro TTS"),
        ("soundfile", "soundfile"),
    ]
    ok = True
    for module, name in deps:
        try:
            __import__(module)
            _ok(name)
        except ImportError:
            _fail(f"{name} not installed",
                  "Run: make install")
            ok = False
    return ok


def check_searxng() -> bool:
    print("[8/8] SearXNG (optional)")
    try:
        import urllib.request
        req = urllib.request.Request("http://127.0.0.1:8080/", method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            if resp.status == 200:
                _ok("SearXNG responding on http://127.0.0.1:8080")
                return True
    except Exception:
        pass

    _warn("SearXNG not reachable on http://127.0.0.1:8080",
          "Start it: cd services/searxng && bash start.sh")
    return False


def main() -> int:
    print("=" * 50)
    print("Local Lucy v10 — Environment Validator")
    print("=" * 50)
    print()

    results = [
        check_python(),
        check_venv(),
        check_ollama(),
        check_models(),
        check_cuda(),
        check_pyside6(),
        check_dependencies(),
        check_searxng(),
    ]

    print()
    print("=" * 50)
    if all(results):
        print("\033[32mAll checks passed. Local Lucy is ready to run.\033[0m")
        print("Launch with:  make run")
        return 0
    elif results[0] and results[2] and results[3]:
        print("\033[33mCore checks passed. Some optional components missing.\033[0m")
        print("Launch with:  make run")
        return 0
    else:
        print("\033[31mCore checks failed. Fix the issues above before running.\033[0m")
        return 1


if __name__ == "__main__":
    sys.exit(main())
