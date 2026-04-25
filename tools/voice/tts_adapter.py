#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from voice.backends import kokoro_backend, piper_backend


class TtsAdapterError(RuntimeError):
    pass


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # pragma: no cover - exercised by main error path
        raise TtsAdapterError(message)


@dataclass(frozen=True)
class SelectedBackend:
    engine: str
    voice: str
    binary: str
    device: str
    fallback_engine: str


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        if args.command == "probe":
            payload = probe_backend(
                requested_engine=args.engine,
                requested_voice=args.voice,
                fallback_engine=args.fallback_engine,
            )
            print_json(payload)
            return 0 if payload.get("ok") else 1
        if args.command == "synthesize":
            text = args.text if args.text is not None else sys.stdin.read()
            payload = synthesize_text(
                text=text,
                requested_engine=args.engine,
                requested_voice=args.voice,
                output_dir=args.output_dir,
                fallback_engine=args.fallback_engine,
            )
            print_json(payload)
            return 0 if payload.get("ok") else 1
        payload = failure_contract(error=f"unsupported command: {args.command}")
        print_json(payload)
        return 1
    except Exception as exc:  # pragma: no cover - top-level safety net
        print_json(failure_contract(error=str(exc)))
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(description="Authoritative Local Lucy TTS synthesis adapter.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    probe = subparsers.add_parser("probe")
    probe.add_argument("--engine", default="auto")
    probe.add_argument("--voice", default="")
    probe.add_argument("--fallback-engine", default="")

    synth = subparsers.add_parser("synthesize")
    synth.add_argument("--engine", default="auto")
    synth.add_argument("--voice", default="")
    synth.add_argument("--output-dir", default="")
    synth.add_argument("--fallback-engine", default="")
    synth.add_argument("--text", default=None)
    return parser


def probe_backend(
    *,
    requested_engine: str | None = None,
    requested_voice: str | None = None,
    fallback_engine: str | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    values = env or os.environ
    requested = normalize_engine(
        requested_engine or values.get("LUCY_VOICE_TTS_ENGINE") or catalog_defaults().get("engine") or "auto"
    )
    available_engines = detect_available_engines(values)
    selected = resolve_selected_backend(
        requested_engine=requested,
        requested_voice=requested_voice,
        fallback_engine=fallback_engine,
        env=values,
    )
    if selected is None:
        error = unavailable_backend_error(requested)
        return {
            "ok": False,
            "requested_engine": requested,
            "engine": "none",
            "device": "none",
            "voice": "",
            "fallback_engine": normalize_engine(fallback_engine or ""),
            "available_engines": available_engines,
            "error": error,
        }
    return {
        "ok": True,
        "requested_engine": requested,
        "engine": selected.engine,
        "device": selected.device,
        "voice": selected.voice,
        "fallback_engine": selected.fallback_engine,
        "available_engines": available_engines,
        "error": "",
    }


def synthesize_text(
    *,
    text: str,
    requested_engine: str | None = None,
    requested_voice: str | None = None,
    output_dir: str | None = None,
    fallback_engine: str | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    values = env or os.environ
    requested = normalize_engine(
        requested_engine or values.get("LUCY_VOICE_TTS_ENGINE") or catalog_defaults().get("engine") or "auto"
    )
    requested_device = resolve_device_for_engine(requested, env=values) if requested in {"piper", "kokoro"} else "none"
    clean = str(text or "").strip()
    if not clean:
        return failure_contract(requested_engine=requested, engine=requested, device=requested_device, error="text is empty")
    selected = resolve_selected_backend(
        requested_engine=requested,
        requested_voice=requested_voice,
        fallback_engine=fallback_engine,
        env=values,
    )
    if selected is None:
        return failure_contract(
            requested_engine=requested,
            engine=requested,
            device=requested_device,
            error=unavailable_backend_error(requested),
        )

    attempts = [selected]
    if selected.engine == requested and selected.fallback_engine and selected.fallback_engine != selected.engine:
        fallback_selected = resolve_explicit_backend(selected.fallback_engine, env=values)
        if fallback_selected is not None and fallback_selected.engine != selected.engine:
            attempts.append(fallback_selected)

    overall_start = now_ms()
    last_error = ""
    for index, attempt in enumerate(attempts):
        output_path: Path | None = None
        try:
            output_path = allocate_output_path(output_dir, values)
            actual_voice = run_backend_synthesis(attempt, clean, output_path, values)
            sample_rate, duration_ms = read_wav_metadata(output_path)
            return {
                "ok": True,
                "requested_engine": requested,
                "engine": attempt.engine,
                "device": attempt.device,
                "voice": actual_voice,
                "wav_path": str(output_path),
                "sample_rate": sample_rate,
                "duration_ms": duration_ms,
                "synth_latency_ms": max(now_ms() - overall_start, 0),
                "fallback_used": index > 0,
                "cache_hit": False,
                "error": "",
            }
        except Exception as exc:
            last_error = str(exc)
            if output_path is not None:
                try:
                    output_path.unlink()
                except OSError:
                    pass
    return failure_contract(
        requested_engine=requested,
        engine=attempts[-1].engine if attempts else requested,
        voice=attempts[-1].voice if attempts else "",
        synth_latency_ms=max(now_ms() - overall_start, 0),
        fallback_used=False,
        error=last_error or "tts synthesis failed",
    )


def run_backend_synthesis(
    selected: SelectedBackend,
    text: str,
    output_path: Path,
    env: Mapping[str, str],
) -> str:
    root = resolve_root()
    if selected.engine == "piper":
        return piper_backend.synthesize(
            root=root,
            text=text,
            output_path=output_path,
            voice=selected.voice,
            env=env,
        )
    if selected.engine == "kokoro":
        return kokoro_backend.synthesize(
            root=root,
            text=text,
            output_path=output_path,
            voice=selected.voice,
            env=env,
    )
    raise TtsAdapterError(f"unsupported backend: {selected.engine}")


def resolve_selected_backend(
    *,
    requested_engine: str,
    requested_voice: str | None,
    fallback_engine: str | None,
    env: Mapping[str, str],
) -> SelectedBackend | None:
    if requested_engine == "auto":
        for engine in auto_order():
            selected = resolve_explicit_backend(engine, requested_voice=requested_voice, fallback_engine=fallback_engine, env=env)
            if selected is not None:
                return selected
        return None
    selected = resolve_explicit_backend(
        requested_engine,
        requested_voice=requested_voice,
        fallback_engine=fallback_engine,
        env=env,
    )
    if selected is not None:
        return selected
    fallback_name = normalize_engine(fallback_engine or catalog_engine(requested_engine).get("fallback_engine") or "")
    if fallback_name and fallback_name != requested_engine:
        return resolve_explicit_backend(fallback_name, env=env)
    return None


def resolve_explicit_backend(
    engine: str,
    *,
    requested_voice: str | None = None,
    fallback_engine: str | None = None,
    env: Mapping[str, str],
) -> SelectedBackend | None:
    normalized = normalize_engine(engine)
    binary = detect_backend_binary(normalized, env)
    if binary is None:
        return None
    voice = resolve_voice_for_engine(normalized, explicit_voice=requested_voice, env=env)
    device = resolve_device_for_engine(normalized, env=env)
    fallback = normalize_engine(fallback_engine or catalog_engine(normalized).get("fallback_engine") or "")
    return SelectedBackend(engine=normalized, voice=voice, binary=str(binary), device=device, fallback_engine=fallback)


def detect_available_engines(env: Mapping[str, str] | None = None) -> list[str]:
    values = env or os.environ
    available: list[str] = []
    for engine in ("piper", "kokoro"):
        if detect_backend_binary(engine, values) is not None:
            available.append(engine)
    return available


def detect_backend_binary(engine: str, env: Mapping[str, str] | None = None) -> Path | None:
    values = env or os.environ
    root = resolve_root()
    if engine == "piper":
        return piper_backend.detect_binary(root, values)
    if engine == "kokoro":
        return kokoro_backend.detect_binary(root, values)
    return None


def resolve_voice_for_engine(engine: str, *, explicit_voice: str | None = None, env: Mapping[str, str] | None = None) -> str:
    values = env or os.environ
    if explicit_voice and explicit_voice.strip():
        return explicit_voice.strip()
    if engine == "piper":
        return piper_backend.resolve_voice_name(values)
    if engine == "kokoro":
        return kokoro_backend.resolve_voice_name(values)
    return ""


def resolve_device_for_engine(engine: str, *, env: Mapping[str, str] | None = None) -> str:
    values = env or os.environ
    if engine == "piper":
        return "cpu"
    if engine == "kokoro":
        return kokoro_backend.resolve_device(values)
    return "none"


def allocate_output_path(raw_output_dir: str | None, env: Mapping[str, str]) -> Path:
    base_dir = resolve_output_dir(raw_output_dir, env)
    base_dir.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "wb",
        delete=False,
        dir=base_dir,
        prefix="voice_tts_",
        suffix=".wav",
    )
    path = Path(handle.name)
    handle.close()
    return path


def resolve_output_dir(raw_output_dir: str | None, env: Mapping[str, str] | None = None) -> Path:
    values = env or os.environ
    explicit = str(raw_output_dir or values.get("LUCY_VOICE_TTS_OUTPUT_DIR", "")).strip()
    if explicit:
        return Path(explicit).expanduser()
    return resolve_root() / "tmp" / "run"


def read_wav_metadata(wav_path: Path) -> tuple[int, int]:
    try:
        with wave.open(str(wav_path), "rb") as handle:
            frame_rate = handle.getframerate()
            frame_count = handle.getnframes()
    except (OSError, EOFError, wave.Error) as exc:
        raise TtsAdapterError(f"unable to read synthesized wav output: {exc}") from exc
    if frame_rate <= 0:
        raise TtsAdapterError("synthesized wav output has invalid sample rate")
    duration_ms = int(round(frame_count * 1000 / frame_rate))
    return frame_rate, max(duration_ms, 0)


def normalize_engine(raw: str | None) -> str:
    value = str(raw or "").strip().lower()
    if value in {"piper", "kokoro", "auto", "none"}:
        return value
    return "auto" if not value else value


def resolve_root() -> Path:
    return Path(__file__).resolve().parents[2]


def catalog_path() -> Path:
    return Path(__file__).resolve().parent / "voices" / "voices.yaml"


def load_catalog() -> dict[str, Any]:
    path = catalog_path()
    raw = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        payload = yaml.safe_load(raw)
    except ModuleNotFoundError:
        payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise TtsAdapterError(f"invalid voice catalog: {path}")
    return payload


def catalog_defaults() -> dict[str, Any]:
    defaults = load_catalog().get("defaults")
    return defaults if isinstance(defaults, dict) else {}


def catalog_engine(engine: str) -> dict[str, Any]:
    payload = load_catalog().get("engines")
    if not isinstance(payload, dict):
        return {}
    engine_payload = payload.get(engine)
    return engine_payload if isinstance(engine_payload, dict) else {}


def auto_order() -> list[str]:
    raw = catalog_defaults().get("auto_order")
    if isinstance(raw, list):
        return [normalize_engine(item) for item in raw if normalize_engine(item) in {"piper", "kokoro"}]
    return ["kokoro", "piper"]


def failure_contract(
    *,
    requested_engine: str = "auto",
    engine: str = "none",
    device: str = "none",
    voice: str = "",
    synth_latency_ms: int = 0,
    fallback_used: bool = False,
    error: str = "",
) -> dict[str, Any]:
    return {
        "ok": False,
        "requested_engine": requested_engine,
        "engine": engine,
        "device": device,
        "voice": voice,
        "wav_path": "",
        "sample_rate": 0,
        "duration_ms": 0,
        "synth_latency_ms": max(synth_latency_ms, 0),
        "fallback_used": bool(fallback_used),
        "cache_hit": False,
        "error": str(error).strip() or "tts synthesis failed",
    }


def unavailable_backend_error(requested_engine: str) -> str:
    if requested_engine not in {"auto", "none"}:
        return f"{requested_engine} backend is not installed or configured"
    return "no configured TTS backend is available"


def now_ms() -> int:
    return int(time.time() * 1000)


def print_json(payload: Mapping[str, Any]) -> None:
    sys.stdout.write(json.dumps(dict(payload), sort_keys=True))
    sys.stdout.write("\n")


if __name__ == "__main__":
    raise SystemExit(main())


# =============================================================================
# TTS Engine Usage Logging
# =============================================================================

class TTSUsageLogger:
    """Logger for TTS engine usage."""
    def __init__(self):
        self.log_dir = Path.home() / ".local" / "share" / "lucy" / "logs"
        self.log_file = self.log_dir / "tts_engine.log"
        self.log_dir.mkdir(parents=True, exist_ok=True)
    
    def log(self, level: str, msg: str):
        from datetime import datetime
        ts = datetime.now().isoformat()
        try:
            with open(self.log_file, "a") as f:
                f.write(f"{ts} [{level}] {msg}\n")
        except Exception:
            pass
    
    def info(self, msg: str):
        self.log("INFO", msg)

_tts_logger = TTSUsageLogger()

# Monkey-patch synthesize_text to log usage
_original_synthesize_text = synthesize_text

def _logged_synthesize_text(*, text: str, requested_engine: str | None = None, **kwargs) -> dict[str, Any]:
    """Wrapper that logs TTS engine selection."""
    result = _original_synthesize_text(text=text, requested_engine=requested_engine, **kwargs)
    
    # Log the engine that was actually used
    actual_engine = result.get("engine", "unknown")
    requested = requested_engine or "auto"
    fallback_used = result.get("fallback_used", False)
    
    _tts_logger.info(f"TTS synthesis: requested={requested}, actual={actual_engine}, fallback={fallback_used}")
    
    return result

# Replace the function
synthesize_text = _logged_synthesize_text
