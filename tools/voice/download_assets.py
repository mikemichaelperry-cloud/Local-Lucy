#!/usr/bin/env python3
"""Voice asset download and verification tool.

This script checks for required voice model assets and can download missing ones.
It does NOT modify STT/TTS runtime logic — it only manages on-disk assets.

Usage:
    python tools/voice/download_assets.py --verify-only
    python tools/voice/download_assets.py --download-all
    python tools/voice/download_assets.py --download-whisper --model small.en
    python tools/voice/download_assets.py --download-piper --voice en_GB-cori-high

Environment overrides:
    LUCY_VOICE_MODEL            Whisper model name (default: small.en)
    LUCY_VOICE_PIPER_VOICE      Piper voice name (default: en_GB-cori-high)
    LUCY_VOICE_INSTALL_PREFIX   Base directory (default: runtime/voice)
    LUCY_VOICE_WHISPER_MODEL_URL   Override download URL
    LUCY_VOICE_PIPER_VOICE_ONNX_URL Override ONNX download URL
    LUCY_VOICE_PIPER_VOICE_JSON_URL Override JSON config download URL
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_WHISPER_MODEL = "small.en"
DEFAULT_PIPER_VOICE = "en_GB-cori-high"
DEFAULT_KOKORO_REPO_ID = "hexgrad/Kokoro-82M"
DEFAULT_KOKORO_VOICE = "af_bella"

WHISPER_BASE_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main"
PIPER_VOICE_BASE_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main"

# Known model sizes (bytes) for validation heuristics
KNOWN_SIZES: dict[str, int] = {
    "ggml-tiny.bin": 77691737,
    "ggml-tiny.en.bin": 77691737,
    "ggml-base.bin": 147964211,
    "ggml-base.en.bin": 147964211,
    "ggml-small.bin": 487614201,
    "ggml-small.en.bin": 487614201,
    "ggml-medium.bin": 1533124773,
    "ggml-medium.en.bin": 1533124773,
    "ggml-large-v3-turbo.bin": 1624555275,
}


def say(msg: str) -> None:
    print(msg)


def warn(msg: str) -> None:
    print(f"WARN: {msg}", file=sys.stderr)


def die(msg: str) -> int:
    print(f"FAIL: {msg}", file=sys.stderr)
    return 1


def resolve_root() -> Path:
    env_root = os.environ.get("LUCY_ROOT", "")
    if env_root:
        return Path(env_root).expanduser().resolve()
    script = Path(__file__).resolve()
    return script.parents[2]


def resolve_install_prefix() -> Path:
    raw = os.environ.get("LUCY_VOICE_INSTALL_PREFIX", "runtime/voice")
    path = Path(raw)
    if path.is_absolute():
        return path
    return resolve_root() / path


def format_size(size_bytes: int) -> str:
    if size_bytes >= 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"
    if size_bytes >= 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes} B"


def download_file(url: str, dest: Path, chunk_size: int = 8192) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    try:
        with urllib.request.urlopen(url, timeout=300) as resp:  # noqa: S310
            with tmp.open("wb") as f:
                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
        tmp.replace(dest)
        return True
    except Exception as exc:
        warn(f"download failed: {exc}")
        try:
            tmp.unlink()
        except OSError:
            pass
        return False


# ---------------------------------------------------------------------------
# Whisper
# ---------------------------------------------------------------------------


def resolve_whisper_model_path(model_name: str, prefix: Path) -> Path:
    return prefix / "models" / f"ggml-{model_name}.bin"


def resolve_whisper_url(model_name: str) -> str:
    env_url = os.environ.get("LUCY_VOICE_WHISPER_MODEL_URL", "")
    if env_url:
        return env_url
    return f"{WHISPER_BASE_URL}/ggml-{model_name}.bin"


def verify_whisper(model_name: str, prefix: Path) -> dict[str, Any]:
    path = resolve_whisper_model_path(model_name, prefix)
    exists = path.exists() and path.is_file()
    size = path.stat().st_size if exists else 0
    known = KNOWN_SIZES.get(f"ggml-{model_name}.bin")
    size_ok = known is None or size == known or size > 1024 * 1024
    return {
        "component": "whisper",
        "model": model_name,
        "path": str(path),
        "exists": exists,
        "size": size,
        "size_formatted": format_size(size),
        "size_known": known,
        "size_ok": size_ok,
        "url": resolve_whisper_url(model_name),
    }


def download_whisper(model_name: str, prefix: Path) -> dict[str, Any]:
    result = verify_whisper(model_name, prefix)
    if result["exists"] and result["size_ok"]:
        say(f"OK: whisper model already present ({result['size_formatted']})")
        return result

    url = result["url"]
    path = Path(result["path"])
    say(f"INFO: downloading whisper model {model_name} from {url}")
    if download_file(url, path):
        result = verify_whisper(model_name, prefix)
        if result["exists"] and result["size_ok"]:
            say(f"OK: whisper model downloaded ({result['size_formatted']})")
        else:
            warn(f"whisper model download size mismatch: {result['size_formatted']}")
    else:
        result["error"] = "download failed"
    return result


# ---------------------------------------------------------------------------
# Piper
# ---------------------------------------------------------------------------


def resolve_piper_model_dir(voice: str, prefix: Path) -> Path:
    return prefix / "models" / "piper" / voice


def resolve_piper_paths(voice: str, prefix: Path) -> tuple[Path, Path]:
    d = resolve_piper_model_dir(voice, prefix)
    return d / f"{voice}.onnx", d / f"{voice}.onnx.json"


def resolve_piper_urls(voice: str) -> tuple[str, str]:
    onnx_env = os.environ.get("LUCY_VOICE_PIPER_VOICE_ONNX_URL", "")
    json_env = os.environ.get("LUCY_VOICE_PIPER_VOICE_JSON_URL", "")
    if onnx_env and json_env:
        return onnx_env, json_env

    # Map default voice to known HF path
    if voice == "en_GB-cori-high":
        base = f"{PIPER_VOICE_BASE_URL}/en/en_GB/cori/high"
        return f"{base}/en_GB-cori-high.onnx", f"{base}/en_GB-cori-high.onnx.json"

    # Generic guess — may not work for all voices
    base = f"{PIPER_VOICE_BASE_URL}"
    return f"{base}/{voice}.onnx", f"{base}/{voice}.onnx.json"


def verify_piper(voice: str, prefix: Path) -> dict[str, Any]:
    onnx_path, json_path = resolve_piper_paths(voice, prefix)
    onnx_exists = onnx_path.exists() and onnx_path.is_file()
    json_exists = json_path.exists() and json_path.is_file()
    onnx_size = onnx_path.stat().st_size if onnx_exists else 0
    json_size = json_path.stat().st_size if json_exists else 0
    onnx_url, json_url = resolve_piper_urls(voice)
    return {
        "component": "piper",
        "voice": voice,
        "onnx_path": str(onnx_path),
        "onnx_exists": onnx_exists,
        "onnx_size": onnx_size,
        "onnx_size_formatted": format_size(onnx_size),
        "json_path": str(json_path),
        "json_exists": json_exists,
        "json_size": json_size,
        "json_size_formatted": format_size(json_size),
        "complete": onnx_exists and json_exists and onnx_size > 0 and json_size > 0,
        "onnx_url": onnx_url,
        "json_url": json_url,
    }


def download_piper(voice: str, prefix: Path) -> dict[str, Any]:
    result = verify_piper(voice, prefix)
    if result["complete"]:
        say(f"OK: piper voice already present ({result['onnx_size_formatted']})")
        return result

    onnx_path = Path(result["onnx_path"])
    json_path = Path(result["json_path"])
    onnx_url = result["onnx_url"]
    json_url = result["json_url"]

    if not result["onnx_exists"]:
        say(f"INFO: downloading piper ONNX from {onnx_url}")
        if not download_file(onnx_url, onnx_path):
            result["error"] = "ONNX download failed"

    if not result["json_exists"]:
        say(f"INFO: downloading piper config from {json_url}")
        if not download_file(json_url, json_path):
            result["error"] = result.get("error", "") + "; JSON download failed"

    result = verify_piper(voice, prefix)
    if result["complete"]:
        say(f"OK: piper voice downloaded ({result['onnx_size_formatted']})")
    return result


# ---------------------------------------------------------------------------
# Kokoro (HF cache verification only — Kokoro manages its own downloads)
# ---------------------------------------------------------------------------


def resolve_kokoro_cache_home(prefix: Path) -> Path:
    raw = os.environ.get("HF_HOME", "") or os.environ.get("LUCY_VOICE_KOKORO_CACHE_HOME", "")
    if raw:
        return Path(raw).expanduser()
    return prefix / "cache" / "huggingface"


def repo_id_to_cache_dir(repo_id: str) -> str:
    return f"models--{repo_id.replace('/', '--')}"


def resolve_kokoro_snapshot(cache_home: Path, repo_id: str) -> Path | None:
    hub_cache = cache_home / "hub"
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


def verify_kokoro(
    prefix: Path,
    repo_id: str = DEFAULT_KOKORO_REPO_ID,
    voice: str = DEFAULT_KOKORO_VOICE,
) -> dict[str, Any]:
    cache_home = resolve_kokoro_cache_home(prefix)
    snapshot = resolve_kokoro_snapshot(cache_home, repo_id)
    snapshot_path = str(snapshot) if snapshot else None

    required_files: list[dict[str, Any]] = []
    all_ready = True

    if snapshot:
        for name in ("config.json", "kokoro-v1_0.pth"):
            path = snapshot / name
            exists = path.exists() and path.is_file()
            size = path.stat().st_size if exists else 0
            required_files.append(
                {
                    "name": name,
                    "path": str(path),
                    "exists": exists,
                    "size": size,
                    "size_formatted": format_size(size),
                }
            )
            if not exists:
                all_ready = False

        voice_path = snapshot / "voices" / f"{voice}.pt"
        voice_exists = voice_path.exists() and voice_path.is_file()
        voice_size = voice_path.stat().st_size if voice_exists else 0
        required_files.append(
            {
                "name": f"voices/{voice}.pt",
                "path": str(voice_path),
                "exists": voice_exists,
                "size": voice_size,
                "size_formatted": format_size(voice_size),
            }
        )
        if not voice_exists:
            all_ready = False
    else:
        all_ready = False

    return {
        "component": "kokoro",
        "repo_id": repo_id,
        "voice": voice,
        "cache_home": str(cache_home),
        "snapshot_path": snapshot_path,
        "files": required_files,
        "ready": all_ready,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download and verify voice model assets for Local Lucy v10."
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Only verify assets; do not download anything.",
    )
    parser.add_argument(
        "--download-all",
        action="store_true",
        help="Download all missing voice assets.",
    )
    parser.add_argument(
        "--download-whisper",
        action="store_true",
        help="Download missing Whisper model.",
    )
    parser.add_argument(
        "--download-piper",
        action="store_true",
        help="Download missing Piper voice model.",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("LUCY_VOICE_MODEL", DEFAULT_WHISPER_MODEL),
        help="Whisper model name (default: small.en).",
    )
    parser.add_argument(
        "--piper-voice",
        default=os.environ.get("LUCY_VOICE_PIPER_VOICE", DEFAULT_PIPER_VOICE),
        help="Piper voice name (default: en_GB-cori-high).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON instead of human-readable text.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    prefix = resolve_install_prefix()
    results: list[dict[str, Any]] = []

    # Determine what to do
    verify_only = args.verify_only
    download_whisper_flag = args.download_whisper or args.download_all
    download_piper_flag = args.download_piper or args.download_all

    # Whisper
    if download_whisper_flag and not verify_only:
        results.append(download_whisper(args.model, prefix))
    else:
        results.append(verify_whisper(args.model, prefix))

    # Piper
    if download_piper_flag and not verify_only:
        results.append(download_piper(args.piper_voice, prefix))
    else:
        results.append(verify_piper(args.piper_voice, prefix))

    # Kokoro (always verify-only; Kokoro downloads via HF hub at runtime)
    results.append(verify_kokoro(prefix))

    # Compute overall health before choosing output format
    all_ok = True
    for r in results:
        comp = r["component"]
        if comp == "whisper":
            status = "OK" if r["exists"] and r["size_ok"] else "MISSING"
            if not r["size_ok"] and r["exists"]:
                status = "SIZE MISMATCH"
            if status != "OK":
                all_ok = False
        elif comp == "piper":
            if not r["complete"]:
                all_ok = False
        elif comp == "kokoro":
            # Kokoro missing is informational, not a hard failure
            pass

    if args.json:
        print(json.dumps({"prefix": str(prefix), "assets": results}, indent=2))
        return 0 if all_ok else 2

    say(f"\nVoice asset report (prefix: {prefix})")
    say("=" * 60)

    for r in results:
        comp = r["component"]
        if comp == "whisper":
            status = "OK" if r["exists"] and r["size_ok"] else "MISSING"
            if not r["size_ok"] and r["exists"]:
                status = "SIZE MISMATCH"
            say(f"\n[{status}] Whisper STT model: {r['model']}")
            say(f"  Path:  {r['path']}")
            say(
                f"  Size:  {r['size_formatted']} {'(expected)' if r['size_known'] else '(unknown expected size)'}"
            )
            say(f"  URL:   {r['url']}")

        elif comp == "piper":
            status = "OK" if r["complete"] else "MISSING"
            say(f"\n[{status}] Piper TTS voice: {r['voice']}")
            say(f"  ONNX:  {r['onnx_path']} ({r['onnx_size_formatted']})")
            say(f"  JSON:  {r['json_path']} ({r['json_size_formatted']})")
            say(f"  ONNX URL: {r['onnx_url']}")
            say(f"  JSON URL: {r['json_url']}")

        elif comp == "kokoro":
            status = "OK" if r["ready"] else "MISSING / NOT CACHED"
            say(f"\n[{status}] Kokoro TTS cache: {r['repo_id']}")
            say(f"  Cache home: {r['cache_home']}")
            say(f"  Snapshot:   {r['snapshot_path'] or 'none'}")
            for f in r.get("files", []):
                fstatus = "OK" if f["exists"] else "MISSING"
                say(f"  [{fstatus}] {f['name']}: {f['size_formatted']}")
            if not r["ready"]:
                say("  NOTE: Kokoro assets are auto-downloaded on first use via HuggingFace hub.")
                say(
                    "        Set HF_HOME or LUCY_VOICE_KOKORO_CACHE_HOME to control cache location."
                )

    say("\n" + "=" * 60)
    if all_ok:
        say("All required voice assets are present.")
        return 0
    else:
        say("Some voice assets are missing.")
        say("Run with --download-all to fetch missing assets.")
        return 2


if __name__ == "__main__":
    sys.exit(main())
