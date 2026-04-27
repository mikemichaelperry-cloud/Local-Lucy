#!/usr/bin/env python3
"""
Comprehensive Local Lucy v8 Benchmark Suite
Runs all automated benchmarks and generates unified report
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# Configuration
SNAPSHOT_ROOT = Path("/home/mike/lucy-v8")
UI_ROOT = Path("/home/mike/lucy-v8/ui-v8")
RUNTIME_NS = Path("/home/mike/.codex-api-home/lucy/runtime-v8")

# Environment setup
os.environ["LUCY_RUNTIME_AUTHORITY_ROOT"] = str(SNAPSHOT_ROOT)
os.environ["LUCY_UI_ROOT"] = str(UI_ROOT)
os.environ["LUCY_RUNTIME_NAMESPACE_ROOT"] = str(RUNTIME_NS)
os.environ["LUCY_RUNTIME_CONTRACT_REQUIRED"] = "1"

REPORT_FILE = Path.home() / "Desktop" / "lucy_v8_benchmark_report.json"


def run_command(cmd, timeout=300, env=None):
    """Run a command and return result"""
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=timeout, env=full_env
        )
        return {
            "success": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "timeout"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def check_prerequisites():
    """Check that runtime is ready"""
    print("=" * 60)
    print("CHECKING PREREQUISITES")
    print("=" * 60)
    
    checks = {}
    
    # Check env vars
    checks["env_authority"] = bool(os.environ.get("LUCY_RUNTIME_AUTHORITY_ROOT"))
    checks["env_ui"] = bool(os.environ.get("LUCY_UI_ROOT"))
    checks["env_runtime_ns"] = bool(os.environ.get("LUCY_RUNTIME_NAMESPACE_ROOT"))
    
    # Check paths exist
    checks["path_snapshot"] = SNAPSHOT_ROOT.exists()
    checks["path_ui"] = UI_ROOT.exists()
    checks["path_runtime"] = RUNTIME_NS.exists()
    
    # Check Ollama
    result = run_command("ollama list 2>/dev/null | grep -q local-lucy")
    checks["ollama_model"] = result["success"]
    
    # Check TTS engines
    result = run_command(f"cd {SNAPSHOT_ROOT} && python3 -c \"import sys; sys.path.insert(0, 'tools'); from voice.backends import kokoro_backend; print(kokoro_backend.detect_binary({SNAPSHOT_ROOT!r}) is not None)\"")
    checks["tts_kokoro"] = "True" in result.get("stdout", "")
    
    # Check if Kokoro worker is running
    result = run_command("pgrep -f kokoro_session_worker >/dev/null && echo 'running' || echo 'stopped'")
    checks["kokoro_worker"] = "running" in result.get("stdout", "")
    
    # Check whisper model
    whisper_model = SNAPSHOT_ROOT / "runtime/voice/models/ggml-small.en.bin"
    checks["whisper_model"] = whisper_model.exists()
    
    for check, status in checks.items():
        icon = "✓" if status else "✗"
        print(f"  {icon} {check}")
    
    all_ok = all(checks.values())
    if not all_ok:
        print("\n⚠ Some prerequisites not met - continuing anyway")
    
    return checks


def benchmark_text_latency():
    """Run text latency benchmark"""
    print("\n" + "=" * 60)
    print("PHASE 1: TEXT LATENCY")
    print("=" * 60)
    
    prompts = [
        "What is Ohm's law?",
        "Explain entropy simply.",
        "What is a diode?",
    ]
    
    results = []
    tool = SNAPSHOT_ROOT / "tools/runtime_request.py"
    
    for prompt in prompts:
        print(f"\n  Testing: '{prompt[:40]}...'")
        times = []
        for run in range(1, 3):
            start = time.time()
            result = run_command(
                f"python3 {tool} submit --text '{prompt}'", 
                timeout=130
            )
            elapsed = time.time() - start
            
            if result["success"]:
                times.append(elapsed)
                print(f"    Run {run}: {elapsed:.2f}s")
            else:
                print(f"    Run {run}: FAILED")
        
        if times:
            results.append({
                "prompt": prompt,
                "median_ttc": round(sorted(times)[len(times)//2], 2),
                "min": round(min(times), 2),
                "max": round(max(times), 2)
            })
    
    return results


def benchmark_tts():
    """Run TTS benchmark"""
    print("\n" + "=" * 60)
    print("PHASE 2: TTS LATENCY")
    print("=" * 60)
    
    tool = SNAPSHOT_ROOT / "tools/voice/bench_tts_latency.py"
    result = run_command(
        f"cd {SNAPSHOT_ROOT} && python3 {tool} --runs 2",
        timeout=180
    )
    
    if result["success"]:
        try:
            # Parse JSON output
            data = json.loads(result["stdout"])
            return {
                "variants_tested": data.get("variants", []),
                "summary": data.get("summary", {})
            }
        except json.JSONDecodeError:
            return {"error": "Could not parse results", "raw": result["stdout"][:500]}
    else:
        return {"error": "Benchmark failed", "stderr": result.get("stderr", "")[:500]}


def check_voice_path():
    """Check voice pipeline components"""
    print("\n" + "=" * 60)
    print("PHASE 3: VOICE PIPELINE CHECK")
    print("=" * 60)
    
    checks = {}
    
    # Check voice tools exist
    voice_tools = [
        "tools/runtime_voice.py",
        "tools/voice/tts_adapter.py",
        "tools/voice/playback.py",
        "runtime/voice/bin/whisper"
    ]
    
    for tool in voice_tools:
        path = SNAPSHOT_ROOT / tool
        exists = path.exists()
        checks[tool] = exists
        icon = "✓" if exists else "✗"
        print(f"  {icon} {tool}")
    
    # Check voice state
    result = run_command(f"python3 {SNAPSHOT_ROOT}/tools/runtime_voice.py status")
    checks["voice_status_works"] = result["success"]
    
    return checks


def generate_report(prereqs, text_results, tts_results, voice_checks):
    """Generate unified report"""
    report = {
        "timestamp": datetime.now().isoformat(),
        "snapshot": str(SNAPSHOT_ROOT),
        "ui": str(UI_ROOT),
        "prerequisites": prereqs,
        "text_latency": text_results,
        "tts_latency": tts_results,
        "voice_pipeline": voice_checks,
        "summary": {
            "all_prereqs_met": all(prereqs.values()),
            "text_tests_passed": len([r for r in text_results if "median_ttc" in r]),
            "tts_working": "error" not in tts_results
        }
    }
    
    with open(REPORT_FILE, "w") as f:
        json.dump(report, f, indent=2)
    
    return report


def main():
    print("\n" + "=" * 60)
    print("LOCAL LUCY v7 COMPREHENSIVE BENCHMARK")
    print("=" * 60)
    print(f"Started: {datetime.now().strftime('%H:%M:%S')}")
    print(f"Report will be saved to: {REPORT_FILE}")
    
    # Run all phases
    prereqs = check_prerequisites()
    text_results = benchmark_text_latency()
    tts_results = benchmark_tts()
    voice_checks = check_voice_path()
    
    # Generate report
    report = generate_report(prereqs, text_results, tts_results, voice_checks)
    
    # Print summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  Prerequisites met: {report['summary']['all_prereqs_met']}")
    print(f"  Text tests passed: {report['summary']['text_tests_passed']}/{len(text_results)}")
    print(f"  TTS working: {report['summary']['tts_working']}")
    
    if text_results:
        print("\n  Text Latency (median TTC):")
        for r in text_results:
            if "median_ttc" in r:
                print(f"    {r['prompt'][:30]:30} {r['median_ttc']:5.2f}s")
    
    print(f"\n  Full report: {REPORT_FILE}")
    print("\n" + "=" * 60)
    print("NEXT STEPS FOR MANUAL TESTING:")
    print("=" * 60)
    print("  1. Launch HMI: cd /home/mike/lucy-v8/ui-v8 && source .venv/bin/activate && python app/main.py")
    print("  2. Enable voice mode")
    print("  3. Run 10 voice turns, watch for:")
    print("     - Clipped first words")
    print("     - Repeated sentences")
    print("     - Long delays before speech")
    print("     - Piper fallback (indicates Kokoro failure)")
    print("=" * 60)


if __name__ == "__main__":
    main()
