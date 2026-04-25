#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from voice import playback, tts_adapter
from voice.backends import kokoro_backend


UTTERANCES = [
    ("short", "Lucy status nominal."),
    ("medium", "Local Lucy is running a controlled text to speech latency check."),
    (
        "long",
        "This is a longer speech sample intended to represent realistic operator feedback and help identify synthesis, file, and playback overhead in the current voice pipeline.",
    ),
]


@dataclass(frozen=True)
class BackendVariant:
    name: str
    engine: str
    env_updates: dict[str, str]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output_dir = Path(args.output_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)

    variants = select_variants()
    payload: dict[str, Any] = {
        "runs_per_text": args.runs,
        "output_dir": str(output_dir),
        "player": playback.detect_audio_player() or "none",
        "first_audible_note": "not directly measurable; playback_start_proxy_ms is player process dispatch time only",
        "utterances": [{"id": item_id, "text": text} for item_id, text in UTTERANCES],
        "variants": [variant.name for variant in variants],
        "results": [],
        "summary": {},
    }

    for variant in variants:
        cold_done = False
        clear_variant_state(variant)
        for text_id, text in UTTERANCES:
            for run_index in range(args.runs):
                cold = not cold_done
                result = benchmark_one(
                    variant=variant,
                    text_id=text_id,
                    text=text,
                    run_index=run_index + 1,
                    cold=cold,
                    output_dir=output_dir,
                )
                payload["results"].append(result)
                cold_done = True

    payload["summary"] = summarize(payload["results"])
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    if args.json_out:
        Path(args.json_out).expanduser().write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a narrow TTS latency pass against the Local Lucy v7 adapter seam.")
    parser.add_argument("--runs", type=int, default=3, help="Runs per backend/text combination.")
    parser.add_argument(
        "--output-dir",
        default=str(tts_adapter.resolve_root() / "tmp" / "run"),
        help="Directory for temporary synthesized wav files.",
    )
    parser.add_argument("--json-out", default="", help="Optional path to write the full JSON benchmark payload.")
    return parser.parse_args(argv)


def select_variants() -> list[BackendVariant]:
    variants: list[BackendVariant] = []
    base_env = os.environ.copy()
    
    # Check for Kokoro - either via Python module or session worker
    kokoro_available = backend_available("kokoro", base_env)
    if not kokoro_available:
        # Check for running session worker as fallback
        socket_path = Path(os.environ.get("LUCY_VOICE_KOKORO_SOCKET", 
                                         "/home/mike/lucy/snapshots/opt-experimental-v7-dev/tmp/run/kokoro_tts_worker.sock"))
        if socket_path.exists():
            kokoro_available = True
    
    if kokoro_available:
        variants.append(BackendVariant(name="kokoro", engine="kokoro", env_updates={}))
        variants.append(BackendVariant(name="kokoro-cpu", engine="kokoro", env_updates={"LUCY_VOICE_KOKORO_DEVICE": "cpu"}))
        if kokoro_backend.cuda_available():
            variants.append(
                BackendVariant(name="kokoro-cuda", engine="kokoro", env_updates={"LUCY_VOICE_KOKORO_DEVICE": "cuda"})
            )
    
    if backend_available("piper", base_env):
        variants.append(BackendVariant(name="piper", engine="piper", env_updates={}))

    if not variants:
        raise SystemExit("No benchmarkable TTS backends are available")
    return variants


def backend_available(engine: str, env: dict[str, str]) -> bool:
    payload = tts_adapter.probe_backend(requested_engine=engine, fallback_engine="none", env=env)
    return bool(payload.get("ok"))


def clear_variant_state(variant: BackendVariant) -> None:
    if variant.engine == "kokoro":
        kokoro_backend._PIPELINE_CACHE.clear()


def benchmark_one(
    *,
    variant: BackendVariant,
    text_id: str,
    text: str,
    run_index: int,
    cold: bool,
    output_dir: Path,
) -> dict[str, Any]:
    env = os.environ.copy()
    env.update(variant.env_updates)

    timings: dict[str, float] = {}
    notes: list[str] = []

    original_allocate_output_path = tts_adapter.allocate_output_path
    original_run_backend_synthesis = tts_adapter.run_backend_synthesis
    original_read_wav_metadata = tts_adapter.read_wav_metadata
    original_load_runtime_dependencies = kokoro_backend.load_runtime_dependencies
    original_get_pipeline = kokoro_backend.get_pipeline
    original_synthesize_audio = kokoro_backend.synthesize_audio

    synth_start = time.perf_counter()
    backend_started_at: float | None = None

    def wrapped_allocate_output_path(raw_output_dir: str | None, values: dict[str, str]) -> Path:
        begin = time.perf_counter()
        path = original_allocate_output_path(raw_output_dir, values)
        timings["wav_path_alloc_ms"] = elapsed_ms(begin)
        return path

    def wrapped_run_backend_synthesis(selected: tts_adapter.SelectedBackend, clean_text: str, output_path: Path, values: dict[str, str]) -> str:
        nonlocal backend_started_at
        backend_started_at = time.perf_counter()
        timings["backend_engine"] = selected.engine  # type: ignore[assignment]
        begin = backend_started_at
        try:
            return original_run_backend_synthesis(selected, clean_text, output_path, values)
        finally:
            timings["backend_total_ms"] = elapsed_ms(begin)

    def wrapped_read_wav_metadata(wav_path: Path) -> tuple[int, int]:
        begin = time.perf_counter()
        result = original_read_wav_metadata(wav_path)
        timings["wav_metadata_read_ms"] = elapsed_ms(begin)
        return result

    def wrapped_load_runtime_dependencies() -> tuple[Any, Any, Any]:
        KPipeline, np_module, soundfile_module = original_load_runtime_dependencies()

        class TimedSoundFile:
            @staticmethod
            def write(path: str, data: Any, sample_rate: int, subtype: str | None = None) -> Any:
                begin = time.perf_counter()
                try:
                    return soundfile_module.write(path, data, sample_rate, subtype=subtype)
                finally:
                    timings["wav_write_ms"] = timings.get("wav_write_ms", 0.0) + elapsed_ms(begin)

        return KPipeline, np_module, TimedSoundFile

    def wrapped_get_pipeline(*args: Any, **kwargs: Any) -> Any:
        begin = time.perf_counter()
        lang_code = str(kwargs.get("lang_code", args[0] if args else ""))
        repo_id = str(kwargs.get("repo_id", ""))
        device = str(kwargs.get("device", ""))
        cache_key = (lang_code, repo_id, device)
        timings["backend_init_cache_hit"] = 1.0 if cache_key in kokoro_backend._PIPELINE_CACHE else 0.0
        try:
            return original_get_pipeline(*args, **kwargs)
        finally:
            timings["backend_init_load_ms"] = elapsed_ms(begin)

    def wrapped_synthesize_audio(*args: Any, **kwargs: Any) -> Any:
        begin = time.perf_counter()
        try:
            return original_synthesize_audio(*args, **kwargs)
        finally:
            timings["backend_synthesis_ms"] = elapsed_ms(begin)

    tts_adapter.allocate_output_path = wrapped_allocate_output_path
    tts_adapter.run_backend_synthesis = wrapped_run_backend_synthesis
    tts_adapter.read_wav_metadata = wrapped_read_wav_metadata
    if variant.engine == "kokoro":
        kokoro_backend.load_runtime_dependencies = wrapped_load_runtime_dependencies
        kokoro_backend.get_pipeline = wrapped_get_pipeline
        kokoro_backend.synthesize_audio = wrapped_synthesize_audio

    try:
        payload = tts_adapter.synthesize_text(
            text=text,
            requested_engine=variant.engine,
            output_dir=str(output_dir),
            fallback_engine="none",
            env=env,
        )
    finally:
        tts_adapter.allocate_output_path = original_allocate_output_path
        tts_adapter.run_backend_synthesis = original_run_backend_synthesis
        tts_adapter.read_wav_metadata = original_read_wav_metadata
        kokoro_backend.load_runtime_dependencies = original_load_runtime_dependencies
        kokoro_backend.get_pipeline = original_get_pipeline
        kokoro_backend.synthesize_audio = original_synthesize_audio

    timings["adapter_total_ms"] = elapsed_ms(synth_start)
    timings["adapter_dispatch_ms"] = (
        max((backend_started_at - synth_start) * 1000.0, 0.0) if backend_started_at is not None else None
    )  # type: ignore[assignment]

    result: dict[str, Any] = {
        "variant": variant.name,
        "engine_request": variant.engine,
        "text_id": text_id,
        "run_index": run_index,
        "cold": cold,
        "ok": bool(payload.get("ok")),
        "requested_engine": payload.get("requested_engine"),
        "engine": payload.get("engine"),
        "voice": payload.get("voice"),
        "sample_rate": payload.get("sample_rate"),
        "duration_ms": payload.get("duration_ms"),
        "adapter_contract_synth_latency_ms": payload.get("synth_latency_ms"),
        "timings_ms": normalize_timings(timings, variant.engine),
        "notes": notes,
    }

    wav_path = Path(str(payload.get("wav_path") or "")).expanduser()
    if not payload.get("ok"):
        result["error"] = payload.get("error")
        result["notes"].append("synthesis failed; playback not measured")
        return result

    playback_metrics = benchmark_playback(wav_path, variant.engine, env)
    result["playback"] = playback_metrics
    result["timings_ms"]["total_end_to_end_ms"] = round(
        result["timings_ms"]["adapter_total_ms"] + playback_metrics["playback_total_ms"], 3
    )
    result["first_audible_proxy"] = "player_process_dispatch"

    if variant.engine == "piper":
        result["notes"].append("backend init/load, core synthesis, and wav write are not separable inside the CLI backend process")
    if variant.engine == "kokoro" and timings.get("backend_init_cache_hit", 0.0) >= 1.0:
        result["notes"].append("kokoro pipeline cache hit")
    if cold:
        result["notes"].append("first run for this backend variant after cache clear")
    return result


def benchmark_playback(wav_path: Path, engine: str, env: dict[str, str]) -> dict[str, Any]:
    player = playback.detect_audio_player()
    if not player:
        return {"player": "none", "playback_prepare_ms": None, "playback_start_proxy_ms": None, "playback_total_ms": None}

    prepad_ms = 0
    if engine == "piper":
        raw_prepad = str(env.get("LUCY_VOICE_PIPER_PREPAD_MS", "")).strip() or "80"
        if raw_prepad.isdigit():
            prepad_ms = int(raw_prepad)
    elif engine == "kokoro":
        raw_prepad = str(env.get("LUCY_VOICE_KOKORO_FIRST_CHUNK_PREPAD_MS", "")).strip() or "220"
        if raw_prepad.isdigit():
            prepad_ms = int(raw_prepad)

    prepare_begin = time.perf_counter()
    temp_path: Path | None = None
    playback_path = wav_path
    if prepad_ms > 0:
        temp_path = playback.create_prepadded_copy(wav_path, prepad_ms)
        playback_path = temp_path
    playback_prepare_ms = elapsed_ms(prepare_begin)

    if player == "aplay":
        command = ["aplay", "-q", str(playback_path)]
    else:
        command = ["paplay", str(playback_path)]

    started = time.perf_counter()
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=False)
    start_proxy_ms = elapsed_ms(started)
    try:
        process.wait(timeout=120)
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except OSError:
                pass
        try:
            wav_path.unlink()
        except OSError:
            pass
    playback_total_ms = elapsed_ms(started)
    return {
        "player": player,
        "playback_prepare_ms": round(playback_prepare_ms, 3),
        "playback_start_proxy_ms": round(start_proxy_ms, 3),
        "playback_total_ms": round(playback_total_ms, 3),
    }


def normalize_timings(timings: dict[str, float], engine: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "adapter_dispatch_ms": rounded_or_none(timings.get("adapter_dispatch_ms")),
        "adapter_total_ms": rounded_or_none(timings.get("adapter_total_ms")),
        "backend_init_load_ms": rounded_or_none(timings.get("backend_init_load_ms")),
        "backend_synthesis_ms": rounded_or_none(timings.get("backend_synthesis_ms")),
        "backend_total_ms": rounded_or_none(timings.get("backend_total_ms")),
        "wav_write_ms": rounded_or_none(timings.get("wav_write_ms")),
        "wav_metadata_read_ms": rounded_or_none(timings.get("wav_metadata_read_ms")),
        "wav_path_alloc_ms": rounded_or_none(timings.get("wav_path_alloc_ms")),
    }
    if engine == "kokoro":
        payload["backend_init_cache_hit"] = bool(timings.get("backend_init_cache_hit", 0.0))
    else:
        payload["backend_init_cache_hit"] = None
    return payload


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    by_variant: dict[str, list[dict[str, Any]]] = defaultdict(list)
    cold_runs: dict[str, dict[str, Any]] = {}

    for item in results:
        grouped[(str(item["variant"]), str(item["text_id"]))].append(item)
        by_variant[str(item["variant"])].append(item)
        if item.get("cold") and str(item["variant"]) not in cold_runs:
            cold_runs[str(item["variant"])] = item

    payload: dict[str, Any] = {"by_variant_text": {}, "cold_notes": {}}
    for (variant, text_id), items in grouped.items():
        payload["by_variant_text"][f"{variant}:{text_id}"] = aggregate_runs(items)
    for variant, items in by_variant.items():
        payload["by_variant_text"][f"{variant}:all"] = aggregate_runs(items)
    for variant, item in cold_runs.items():
        payload["cold_notes"][variant] = {
            "text_id": item["text_id"],
            "adapter_total_ms": item["timings_ms"]["adapter_total_ms"],
            "backend_init_load_ms": item["timings_ms"]["backend_init_load_ms"],
            "backend_total_ms": item["timings_ms"]["backend_total_ms"],
            "playback_total_ms": (item.get("playback") or {}).get("playback_total_ms"),
            "total_end_to_end_ms": item["timings_ms"].get("total_end_to_end_ms"),
        }
    return payload


def aggregate_runs(items: list[dict[str, Any]]) -> dict[str, Any]:
    metrics = [
        "adapter_dispatch_ms",
        "adapter_total_ms",
        "backend_init_load_ms",
        "backend_synthesis_ms",
        "backend_total_ms",
        "wav_write_ms",
        "wav_metadata_read_ms",
        "wav_path_alloc_ms",
        "total_end_to_end_ms",
    ]
    playback_metrics = [
        "playback_prepare_ms",
        "playback_start_proxy_ms",
        "playback_total_ms",
    ]

    payload: dict[str, Any] = {
        "run_count": len(items),
        "successful_runs": sum(1 for item in items if item.get("ok")),
        "warm_run_count": sum(1 for item in items if not item.get("cold")),
        "metrics_ms": {},
        "playback_ms": {},
    }

    for metric in metrics:
        values = [to_float(item["timings_ms"].get(metric)) for item in items]
        payload["metrics_ms"][metric] = stats_dict(values)

    for metric in playback_metrics:
        values = [to_float((item.get("playback") or {}).get(metric)) for item in items]
        payload["playback_ms"][metric] = stats_dict(values)

    warm_items = [item for item in items if not item.get("cold")]
    payload["warm_metrics_ms"] = {}
    for metric in metrics:
        values = [to_float(item["timings_ms"].get(metric)) for item in warm_items]
        payload["warm_metrics_ms"][metric] = stats_dict(values)
    return payload


def stats_dict(values: list[float | None]) -> dict[str, Any]:
    clean = [value for value in values if value is not None]
    if not clean:
        return {"median": None, "mean": None, "min": None, "max": None}
    return {
        "median": round(statistics.median(clean), 3),
        "mean": round(statistics.mean(clean), 3),
        "min": round(min(clean), 3),
        "max": round(max(clean), 3),
    }


def to_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def rounded_or_none(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 3)


def elapsed_ms(start: float) -> float:
    return max((time.perf_counter() - start) * 1000.0, 0.0)


if __name__ == "__main__":
    raise SystemExit(main())
