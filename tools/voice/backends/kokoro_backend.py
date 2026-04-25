from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import sys
import warnings
from pathlib import Path
from typing import Any, Mapping


DEFAULT_REPO_ID = "hexgrad/Kokoro-82M"
DEFAULT_SAMPLE_RATE = 24000
KNOWN_WARNING_PATTERNS = (
    r"dropout option adds dropout after all but last recurrent layer",
    r"`torch\.nn\.utils\.weight_norm` is deprecated",
)
SUPPORTED_LANG_CODES = {"a", "b", "e", "f", "h", "i", "j", "p", "z"}
LANGUAGE_ALIASES = {
    "a": "a",
    "b": "b",
    "e": "e",
    "f": "f",
    "h": "h",
    "i": "i",
    "j": "j",
    "p": "p",
    "z": "z",
    "en-us": "a",
    "en-gb": "b",
}
_PIPELINE_CACHE: dict[tuple[str, str, str], Any] = {}


class KokoroBackendError(RuntimeError):
    pass


def detect_binary(root: Path, env: Mapping[str, str] | None = None) -> Path | None:
    values = env or os.environ
    explicit = str(values.get("LUCY_VOICE_KOKORO_BIN", "")).strip()
    if explicit:
        path = Path(explicit).expanduser()
        return path if path.exists() else None
    
    # Check if kokoro module is available in current Python
    if importlib.util.find_spec("kokoro") is not None and importlib.util.find_spec("soundfile") is not None:
        return Path(sys.executable)
    
    # Check for socket-based worker (runs in separate Python process)
    socket_path = root / "tmp" / "run" / "kokoro_tts_worker.sock"
    if socket_path.exists():
        # Verify socket is responsive
        try:
            import socket
            import json
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(2)
            sock.connect(str(socket_path))
            sock.send(json.dumps({"cmd": "prewarm"}).encode() + b"\n")
            response = sock.recv(4096).decode()
            sock.close()
            result = json.loads(response)
            if result.get("ok"):
                # Return ui-v8 Python path since that's where Kokoro is installed
                ui_v8_python = root.parent.parent / "ui-v8" / ".venv" / "bin" / "python3"
                if ui_v8_python.exists():
                    return ui_v8_python
        except Exception:
            pass
    
    return None


def resolve_voice_name(env: Mapping[str, str] | None = None, explicit_voice: str | None = None) -> str:
    if explicit_voice and explicit_voice.strip():
        return explicit_voice.strip()
    values = env or os.environ
    return str(values.get("LUCY_VOICE_KOKORO_VOICE", "")).strip() or "af_bella"


def synthesize(
    *,
    root: Path,
    text: str,
    output_path: Path,
    voice: str | None = None,
    env: Mapping[str, str] | None = None,
    timeout_seconds: int = 90,
) -> str:
    del timeout_seconds
    values = env or os.environ
    if detect_binary(root, values) is None:
        raise KokoroBackendError("kokoro backend is not installed or configured")

    resolved_voice = resolve_voice_name(values, voice)
    try:
        configure_runtime_environment(root, values)
        lang_code = resolve_lang_code(values, resolved_voice)
        pipeline = get_pipeline(
            lang_code=lang_code,
            repo_id=resolve_repo_id(values),
            device=resolve_device(values),
        )
        _, np_module, soundfile_module = load_runtime_dependencies()
        audio = synthesize_audio(
            pipeline=pipeline,
            text=text,
            voice=resolved_voice,
            speed=resolve_speed(values),
            split_pattern=resolve_split_pattern(values),
            np_module=np_module,
        )
        soundfile_module.write(str(output_path), audio, DEFAULT_SAMPLE_RATE, subtype="PCM_16")
    except KokoroBackendError:
        raise
    except Exception as exc:
        raise KokoroBackendError(f"kokoro synthesis failed: {exc}") from exc
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise KokoroBackendError("kokoro synthesis produced no wav output")
    return resolved_voice


def load_runtime_dependencies() -> tuple[Any, Any, Any]:
    try:
        from kokoro import KPipeline
        import numpy as np
        import soundfile as sf
    except Exception as exc:  # pragma: no cover - exercised in live/runtime environments
        raise KokoroBackendError(f"unable to import kokoro runtime: {exc}") from exc
    return KPipeline, np, sf


def get_pipeline(*, lang_code: str, repo_id: str, device: str) -> Any:
    cache_key = (lang_code, repo_id, device)
    cached = _PIPELINE_CACHE.get(cache_key)
    if cached is not None:
        return cached
    KPipeline, _, _ = load_runtime_dependencies()
    try:
        with suppress_kokoro_noise():
            pipeline = KPipeline(lang_code=lang_code, repo_id=repo_id, device=device)
    except Exception as exc:
        raise KokoroBackendError(f"unable to initialize kokoro pipeline: {exc}") from exc
    _PIPELINE_CACHE[cache_key] = pipeline
    return pipeline


def synthesize_audio(
    *,
    pipeline: Any,
    text: str,
    voice: str,
    speed: float,
    split_pattern: str,
    np_module: Any,
) -> Any:
    chunks: list[Any] = []
    try:
        with suppress_kokoro_noise():
            for result in pipeline(text, voice=voice, speed=speed, split_pattern=split_pattern):
                audio = getattr(result, "audio", None)
                chunk = coerce_audio_chunk(audio, np_module)
                if chunk is not None and getattr(chunk, "size", 0) > 0:
                    chunks.append(chunk)
    except Exception as exc:
        raise KokoroBackendError(f"kokoro synthesis failed: {exc}") from exc
    if not chunks:
        raise KokoroBackendError("kokoro synthesis produced no audio frames")
    merged = np_module.concatenate(chunks) if len(chunks) > 1 else chunks[0]
    return np_module.clip(merged, -1.0, 1.0)


def coerce_audio_chunk(audio: Any, np_module: Any) -> Any | None:
    if audio is None:
        return None
    if hasattr(audio, "detach"):
        audio = audio.detach().cpu().numpy()
    chunk = np_module.asarray(audio, dtype=np_module.float32)
    if getattr(chunk, "ndim", 0) == 0:
        return chunk.reshape(1)
    return chunk.reshape(-1)


def resolve_lang_code(env: Mapping[str, str], voice: str) -> str:
    explicit = normalize_lang_code(str(env.get("LUCY_VOICE_KOKORO_LANG_CODE", "")).strip())
    if explicit:
        return explicit
    trimmed = voice.strip().lower()
    if trimmed.endswith(".pt"):
        raise KokoroBackendError("kokoro language code is required when using a custom voice tensor")
    inferred = normalize_lang_code(trimmed[:1])
    if inferred:
        return inferred
    raise KokoroBackendError(f"unable to infer kokoro language code for voice: {voice}")


def normalize_lang_code(raw: str) -> str:
    return LANGUAGE_ALIASES.get(str(raw or "").strip().lower(), "")


def resolve_repo_id(env: Mapping[str, str]) -> str:
    return str(env.get("LUCY_VOICE_KOKORO_REPO_ID", "")).strip() or DEFAULT_REPO_ID


def resolve_device(env: Mapping[str, str]) -> str:
    value = str(env.get("LUCY_VOICE_KOKORO_DEVICE", "")).strip().lower()
    if value in {"cpu", "cuda"}:
        return value
    return "cuda" if cuda_available() else "cpu"


def cuda_available() -> bool:
    try:
        import torch
    except Exception:
        return False
    try:
        return bool(torch.cuda.is_available())
    except Exception:
        return False


def resolve_speed(env: Mapping[str, str]) -> float:
    raw = str(env.get("LUCY_VOICE_KOKORO_SPEED", "")).strip()
    if not raw:
        return 1.0
    try:
        value = float(raw)
    except ValueError:
        return 1.0
    return value if value > 0 else 1.0


def resolve_split_pattern(env: Mapping[str, str]) -> str:
    return str(env.get("LUCY_VOICE_KOKORO_SPLIT_PATTERN", "")).strip() or r"\n+"


def configure_runtime_environment(root: Path, env: Mapping[str, str]) -> None:
    hf_home_raw = str(env.get("HF_HOME", "")).strip() or str(env.get("LUCY_VOICE_KOKORO_CACHE_HOME", "")).strip()
    hf_home = Path(hf_home_raw).expanduser() if hf_home_raw else root / "runtime" / "voice" / "cache" / "huggingface"
    hub_cache_raw = str(env.get("HF_HUB_CACHE", "")).strip()
    transformers_cache_raw = str(env.get("TRANSFORMERS_CACHE", "")).strip()
    hub_cache = Path(hub_cache_raw).expanduser() if hub_cache_raw else hf_home / "hub"
    transformers_cache = (
        Path(transformers_cache_raw).expanduser() if transformers_cache_raw else hf_home / "transformers"
    )
    hf_home.mkdir(parents=True, exist_ok=True)
    hub_cache.mkdir(parents=True, exist_ok=True)
    transformers_cache.mkdir(parents=True, exist_ok=True)
    os.environ["HF_HOME"] = str(hf_home)
    os.environ["HF_HUB_CACHE"] = str(hub_cache)
    os.environ["TRANSFORMERS_CACHE"] = str(transformers_cache)
    repo_id = resolve_repo_id(env)
    voice = resolve_voice_name(env)
    if cache_ready(hub_cache, repo_id=repo_id, voice=voice):
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
    else:
        os.environ.pop("HF_HUB_OFFLINE", None)
        os.environ.pop("TRANSFORMERS_OFFLINE", None)
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")


def cache_ready(hub_cache: Path, *, repo_id: str, voice: str) -> bool:
    snapshot = resolve_snapshot_dir(hub_cache, repo_id)
    if snapshot is None:
        return False
    required = [
        snapshot / "config.json",
        snapshot / "kokoro-v1_0.pth",
    ]
    if voice.endswith(".pt"):
        required.append(Path(voice).expanduser())
    else:
        required.append(snapshot / "voices" / f"{voice}.pt")
    return all(path.exists() and path.is_file() for path in required)


def resolve_snapshot_dir(hub_cache: Path, repo_id: str) -> Path | None:
    repo_cache = hub_cache / repo_id_to_cache_dir(repo_id)
    ref_path = repo_cache / "refs" / "main"
    if not ref_path.exists():
        return None
    try:
        revision = ref_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not revision:
        return None
    snapshot = repo_cache / "snapshots" / revision
    return snapshot if snapshot.exists() else None


def repo_id_to_cache_dir(repo_id: str) -> str:
    return f"models--{repo_id.replace('/', '--')}"


@contextlib.contextmanager
def suppress_stdout():
    with contextlib.redirect_stdout(io.StringIO()):
        yield


@contextlib.contextmanager
def suppress_kokoro_noise():
    with suppress_stdout(), warnings.catch_warnings():
        for pattern in KNOWN_WARNING_PATTERNS:
            warnings.filterwarnings("ignore", message=pattern)
        yield
