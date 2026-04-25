from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Mapping


class PiperBackendError(RuntimeError):
    pass


def detect_binary(root: Path, env: Mapping[str, str] | None = None) -> Path | None:
    values = env or os.environ
    explicit = str(values.get("LUCY_VOICE_PIPER_BIN", "")).strip()
    if explicit:
        path = Path(explicit).expanduser()
        return path if path.exists() else None
    bundled = root / "runtime" / "voice" / "bin" / "piper"
    if bundled.exists():
        return bundled
    system = shutil.which("piper")
    return Path(system) if system else None


def resolve_voice_name(env: Mapping[str, str] | None = None, explicit_voice: str | None = None) -> str:
    if explicit_voice and explicit_voice.strip():
        return explicit_voice.strip()
    values = env or os.environ
    voice = str(values.get("LUCY_VOICE_PIPER_VOICE", "")).strip()
    return voice or "en_GB-cori-high"


def resolve_model_path(root: Path, voice: str, env: Mapping[str, str] | None = None) -> Path:
    values = env or os.environ
    explicit = str(values.get("LUCY_VOICE_PIPER_MODEL", "")).strip()
    if explicit:
        return Path(explicit).expanduser()
    voice_path = Path(voice).expanduser()
    if voice_path.suffix == ".onnx" or voice_path.exists():
        return voice_path
    return root / "runtime" / "voice" / "models" / "piper" / voice / f"{voice}.onnx"


def synthesize(
    *,
    root: Path,
    text: str,
    output_path: Path,
    voice: str | None = None,
    env: Mapping[str, str] | None = None,
    timeout_seconds: int = 90,
) -> str:
    values = env or os.environ
    backend_bin = detect_binary(root, values)
    if backend_bin is None:
        raise PiperBackendError("piper backend is not installed or configured")

    resolved_voice = resolve_voice_name(values, voice)
    model_path = resolve_model_path(root, resolved_voice, values)
    if not model_path.exists():
        raise PiperBackendError(f"missing piper model: {model_path}")

    args = [str(backend_bin), "--model", str(model_path), "--output_file", str(output_path)]
    maybe_add_numeric_arg(args, "--speaker", values.get("LUCY_VOICE_PIPER_SPEAKER", ""), integer_only=True)
    maybe_add_numeric_arg(args, "--length-scale", values.get("LUCY_VOICE_PIPER_LENGTH_SCALE", ""))
    maybe_add_numeric_arg(args, "--noise-scale", values.get("LUCY_VOICE_PIPER_NOISE_SCALE", ""))
    maybe_add_numeric_arg(args, "--noise-w-scale", values.get("LUCY_VOICE_PIPER_NOISE_W_SCALE", ""))
    maybe_add_numeric_arg(args, "--sentence-silence", values.get("LUCY_VOICE_PIPER_SENTENCE_SILENCE", ""))

    try:
        completed = subprocess.run(
            args,
            check=False,
            input=f"{text}\n",
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise PiperBackendError(f"piper synthesis timed out: {exc}") from exc
    except OSError as exc:
        raise PiperBackendError(f"unable to run piper synthesis: {exc}") from exc

    if completed.returncode != 0:
        stderr = clean_text(completed.stderr)
        stdout = clean_text(completed.stdout)
        detail = stderr or stdout or "piper synthesis failed"
        raise PiperBackendError(detail)
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise PiperBackendError("piper synthesis produced no wav output")
    return resolved_voice


def resolve_sample_rate(model_path: Path, env: Mapping[str, str] | None = None) -> int | None:
    values = env or os.environ
    raw = str(values.get("LUCY_VOICE_PIPER_SAMPLE_RATE", "")).strip()
    if raw.isdigit():
        parsed = int(raw)
        if parsed >= 8000:
            return parsed
    config_path = Path(f"{model_path}.json")
    if not config_path.exists():
        return None
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value = ((payload.get("audio") or {}).get("sample_rate"))
    return value if isinstance(value, int) and value >= 8000 else None


def maybe_add_numeric_arg(args: list[str], flag: str, raw: str | None, *, integer_only: bool = False) -> None:
    value = str(raw or "").strip()
    if not value:
        return
    if integer_only:
        if not value.isdigit():
            return
    else:
        try:
            float(value)
        except ValueError:
            return
    args.extend([flag, value])


def clean_text(value: str | None) -> str:
    return str(value or "").strip()
