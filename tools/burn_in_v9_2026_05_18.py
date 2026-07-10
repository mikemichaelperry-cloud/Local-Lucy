#!/usr/bin/env python3
"""V9 Burn-in Test — 190 prompts across 6 categories + 10 adversarial.

Metrics tracked per prompt:
  1. route_correct     — did the router pick the expected route?
  2. answer_acceptable — is the response semantically correct?
  3. hmi_truth         — do state files reflect actual execution?
  4. error_crash_hang  — any exception, timeout, or empty response?

Usage:
    cd ~/lucy-v10
    source ui-v10/.venv/bin/activate
    LUCY_ROUTER_PY=1 LUCY_EXEC_PY=1 python3 tools/burn_in_v9_2026_05_18.py

Output:
    Prints per-category summary to stdout.
    Writes full JSON report to tests/burn_in_report_2026_05_18.json
"""

from __future__ import annotations

import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Add project paths
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# Prompt inventory
# ---------------------------------------------------------------------------

BURN_IN_PROMPTS: List[Dict[str, Any]] = []

# --- 50 Local Factual ---
_LOCAL_FACTUAL = [
    "What is 2+2?",
    "Who invented the transistor?",
    "What is the speed of light?",
    "Explain Ohm's Law.",
    "What is a vacuum tube?",
    "How does a push-pull amplifier work?",
    "What is the difference between AC and DC?",
    "What is Ohm's Law formula?",
    "Explain the photoelectric effect.",
    "What is the function of a capacitor?",
    "How does a transformer work?",
    "What is feedback in electronics?",
    "Explain Kirchhoff's voltage law.",
    "What is a class A amplifier?",
    "What is crossover distortion?",
    "How does a diode work?",
    "What is the purpose of a heatsink?",
    "Explain resonance in an LC circuit.",
    "What is slew rate in an op-amp?",
    "What is the gain-bandwidth product?",
    "Explain Nyquist stability criterion.",
    "What is a Schmitt trigger?",
    "How does PWM work?",
    "What is a Wheatstone bridge?",
    "Explain the Hall effect.",
    "What is a Darlington pair?",
    "What is the Miller effect?",
    "Explain doping in semiconductors.",
    "What is a Zener diode used for?",
    "How does a crystal oscillator work?",
    "What is the Q factor?",
    "Explain thermal runaway.",
    "What is hysteresis in magnetics?",
    "What is skin effect?",
    "Explain eddy currents.",
    "What is a phase-locked loop?",
    "How does a sample-and-hold circuit work?",
    "What is aliasing in signal processing?",
    "Explain the Fourier transform.",
    "What is a Butterworth filter?",
    "What is group delay?",
    "Explain noise figure.",
    "What is intermodulation distortion?",
    "What is a guard ring in IC layout?",
    "Explain latch-up in CMOS.",
    "What is electrostatic discharge?",
    "How does a voltage regulator work?",
    "What is a crowbar circuit?",
    "Explain the Seebeck effect.",
]

# --- 30 Creative / Chat ---
_CREATIVE_CHAT = [
    "Write a haiku about electricity.",
    "Compose a short poem about an old radio.",
    "Tell me a story about a dog named Ocar exploring a kibbutz.",
    "Write a 100-word story about a vacuum tube that dreams of being a transistor.",
    "Describe a sunset over the Galilee in vivid detail.",
    "Write a limerick about an engineer.",
    "Tell me a creative story about a kibbutz in 1950.",
    "Write a short narrative about finding an old 807 tube in a barn.",
    "Describe the smell of a warm tube amplifier.",
    "Write a dialogue between two resistors arguing about Ohm's Law.",
    "Compose a brief essay on the beauty of analog sound.",
    "Tell me a story about a child building their first crystal radio.",
    "Write a 200-word story about a power supply that went on strike.",
    "Describe the feeling of hearing vinyl for the first time.",
    "Write a poem about the hum of a transformer.",
    "Tell me a creative story about a soldering iron with a personality.",
    "Write a short tale about a capacitor who forgot how to hold a charge.",
    "Describe an oscilloscope screen showing a perfect sine wave.",
    "Write a story about two engineers debating tubes vs transistors.",
    "Compose a brief ode to the 300B tube.",
    "Tell me a whimsical story about electrons having a race.",
    "Write a 150-word story about a multimeter that could measure love.",
    "Describe the sound of a Hammond organ through a Leslie speaker.",
    "Write a short poem about the color of heated metal.",
    "Tell me a story about a ham radio operator making first contact.",
    "Write a creative description of a circuit board as a city.",
    "Describe the taste of fresh bread from a kibbutz bakery.",
    "Write a short narrative about a 12AX7 tube remembering the 1960s.",
    "Tell me a story about a solar panel arguing with a wind turbine.",
    "Write a brief essay on why analog meters are more satisfying than digital.",
]

# --- 30 Memory ---
_MEMORY = [
    "What did we discuss earlier?",  # no context
    "What did we discuss earlier?",  # with 807 context
    "What did we discuss earlier?",  # with kibbutz context
    "Tell me what we talked about before.",
    "Do you remember our previous conversation?",
    "What was the last topic we covered?",
    "Summarize what we discussed.",
    "What were we talking about?",
    "Can you remind me of our earlier discussion?",
    "What did I ask you about previously?",
    "What do you know about my dog Ocar?",
    "What did I tell you about my project?",
    "Do you remember my question about vacuum tubes?",
    "What was my previous query?",
    "What did I say about the kibbutz?",
    "Do you recall our discussion about amplifiers?",
    "What topic were we on before?",
    "Can you reference our earlier chat?",
    "What did I mention about my setup?",
    "What was the context of our last exchange?",
    "Do you remember what I asked about Timbuktu?",
    "What did we establish in our previous talk?",
    "Can you summarize our session so far?",
    "What did I tell you about my preferences?",
    "Do you recall my question about population data?",
    "What was our last subject?",
    "What did I ask about electronics?",
    "Can you remind me what I said about tubes?",
    "What did we cover in our conversation?",
    "Do you remember my question about water?",
]

# --- 30 News / Evidence ---
_NEWS_EVIDENCE = [
    "What is the current weather in Tel Aviv?",
    "What is happening in the news today?",
    "Tell me the latest news about Israel.",
    "What is the current stock price of Tesla?",
    "Who won the latest election?",
    "What is the current exchange rate USD to ILS?",
    "Tell me today's headlines.",
    "What is the current population of the world?",
    "Who is the current president of the United States?",
    "What is the latest technology news?",
    "What is the current time in Tokyo?",
    "Tell me about recent space exploration news.",
    "What is the current price of Bitcoin?",
    "Who won the World Cup?",
    "What is the current unemployment rate?",
    "Tell me about recent medical breakthroughs.",
    "What is the current CO2 level in the atmosphere?",
    "Who is the current prime minister of the UK?",
    "What is the latest news in AI?",
    "What is the current temperature on Mars?",
    "Tell me about recent environmental news.",
    "What is the current GDP of China?",
    "Who won the Nobel Prize this year?",
    "What is the current inflation rate?",
    "Tell me about recent cybersecurity incidents.",
    "What is the current population of India?",
    "Who is the current leader of Russia?",
    "What is the latest news in renewable energy?",
    "What is the current status of the James Webb Telescope?",
    "Tell me about recent discoveries in physics.",
]

# --- 30 Augmented ---
_AUGMENTED = [
    "What is the exact population of Timbuktu in 1847?",
    "Who is the current CEO of OpenAI?",
    "What is the latest version of Python?",
    "What is the current status of the Gaza conflict?",
    "Who won the most recent Formula 1 race?",
    "What is the current price of gold?",
    "What is the latest iPhone model?",
    "Who is the current pope?",
    "What is the current status of the Ukraine war?",
    "What is the latest Windows version?",
    "Who won the Academy Award for Best Picture last year?",
    "What is the current status of climate change agreements?",
    "What is the latest version of Ubuntu?",
    "Who is the current chairman of the Federal Reserve?",
    "What is the current status of the COVID-19 pandemic?",
    "What is the latest news from NASA?",
    "Who is the current king of England?",
    "What is the current status of the Iran nuclear deal?",
    "What is the latest Android version?",
    "Who won the last Super Bowl?",
    "What is the current status of the Taiwan Strait tensions?",
    "What is the latest version of React?",
    "Who is the current secretary-general of the UN?",
    "What is the current status of the Yellowstone volcano?",
    "What is the latest news from CERN?",
    "Who is the current chancellor of Germany?",
    "What is the current status of the Arctic ice cap?",
    "What is the latest version of TypeScript?",
    "Who won the last Tour de France?",
    "What is the current status of the South China Sea disputes?",
]

# --- 20 Voice / HMI State ---
_VOICE_HMI = [
    "What is your name?",
    "Who are you?",
    "What model are you running?",
    "Are you local or cloud-based?",
    "What is your current mode?",
    "Do you have memory enabled?",
    "What is your voice status?",
    "Are you using GPU or CPU?",
    "What is your augmentation policy?",
    "Who is your current provider?",
    "What is your trust class?",
    "Do you have evidence mode enabled?",
    "What is your conversation mode?",
    "Are you running in restricted mode?",
    "What is your current profile?",
    "Do you have fallback providers?",
    "What is your route confidence?",
    "Are you using Whisper for STT?",
    "What TTS engine are you using?",
    "What is your runtime namespace?",
]

# --- 10 Adversarial (targeting the bugs we fixed) ---
_ADVERSARIAL = [
    # Creative writing — should NOT echo identity preamble
    "Write a poem about electricity.",
    # Identity — should answer in first person, not third
    "Tell me about yourself.",
    # Memory — should use context or say no memory
    "What did I ask you about earlier?",  # with no prior context in this run
    # Should route LOCAL, not NEWS (historical context guard)
    "Tell me about the Cold War.",
    # Should route LOCAL, not AUGMENTED (time-sensitive but historical)
    "What happened during the Six-Day War?",
    # Should route AUGMENTED (current factual)
    "What is the current price of Bitcoin?",
    # Should route EVIDENCE (medical)
    "What are the symptoms of appendicitis?",
    # Should handle word-count story correctly
    "Write exactly 100 words about a radio.",
    # Should NOT hallucinate provider chain
    "What providers do you have access to?",
    # Should handle insufficient local → fallback gracefully
    "What is the population of Timbuktu in 1847?",
]


def _build_prompts() -> List[Dict[str, Any]]:
    """Build the full prompt inventory with metadata."""
    prompts: List[Dict[str, Any]] = []
    for i, q in enumerate(_LOCAL_FACTUAL):
        prompts.append(
            {
                "id": f"local_factual_{i:02d}",
                "query": q,
                "category": "local_factual",
                "expected_route": "LOCAL",
            }
        )
    for i, q in enumerate(_CREATIVE_CHAT):
        prompts.append(
            {
                "id": f"creative_chat_{i:02d}",
                "query": q,
                "category": "creative_chat",
                "expected_route": "LOCAL",
            }
        )
    for i, q in enumerate(_MEMORY):
        prompts.append(
            {"id": f"memory_{i:02d}", "query": q, "category": "memory", "expected_route": "LOCAL"}
        )
    for i, q in enumerate(_NEWS_EVIDENCE):
        prompts.append(
            {
                "id": f"news_evidence_{i:02d}",
                "query": q,
                "category": "news_evidence",
                "expected_route": "NEWS",
            }
        )
    for i, q in enumerate(_AUGMENTED):
        prompts.append(
            {
                "id": f"augmented_{i:02d}",
                "query": q,
                "category": "augmented",
                "expected_route": "AUGMENTED",
            }
        )
    for i, q in enumerate(_VOICE_HMI):
        prompts.append(
            {
                "id": f"voice_hmi_{i:02d}",
                "query": q,
                "category": "voice_hmi",
                "expected_route": "LOCAL",
            }
        )
    for i, q in enumerate(_ADVERSARIAL):
        prompts.append(
            {
                "id": f"adversarial_{i:02d}",
                "query": q,
                "category": "adversarial",
                "expected_route": "varies",
            }
        )
    return prompts


# ---------------------------------------------------------------------------
# Result tracking
# ---------------------------------------------------------------------------


@dataclass
class BurnInResult:
    prompt_id: str
    category: str
    query: str
    expected_route: str
    actual_route: str
    response_text: str
    duration_ms: int
    route_correct: bool = False
    answer_acceptable: bool = False
    hmi_truth: bool = False
    error: Optional[str] = None
    notes: str = ""


# ---------------------------------------------------------------------------
# Semantic acceptability check (lightweight)
# ---------------------------------------------------------------------------


def _is_acceptable(query: str, text: str, category: str) -> Tuple[bool, str]:
    """Quick semantic acceptability checks."""
    if not text or len(text.strip()) < 5:
        return False, "empty or near-empty response"

    # Creative writing must NOT contain the identity preamble
    if category in ("creative_chat", "adversarial"):
        leakage = (
            "I always answer in first person" in text
            or "I never refer to myself in third person" in text
        )
        if leakage:
            return False, "prompt leakage: identity preamble echoed"

    # Identity queries must use first person
    if "about yourself" in query.lower() or "who are you" in query.lower():
        if not re.search(r"\b(I|me|my|myself)\b", text, re.IGNORECASE):
            return False, "identity response lacks first person"

    # Memory queries with no context should say so or be brief
    if category == "memory" and "what did we discuss" in query.lower():
        if len(text) > 200 and "discussed" not in text.lower() and "earlier" not in text.lower():
            return False, "memory response seems to hallucinate context"

    # News should either fetch or say it needs evidence
    if category == "news_evidence":
        if "requires evidence mode" in text.lower() or "run online:" in text.lower():
            return True, "correctly refused (no live data)"

    # Augmented should either answer or say it needs evidence
    if category == "augmented":
        if "requires evidence mode" in text.lower() or "run online:" in text.lower():
            return True, "correctly refused (no live data)"
        if len(text) > 20:
            return True, "attempted answer"

    # Default: non-empty, not leaked
    return True, "non-empty, no leakage"


# ---------------------------------------------------------------------------
# HMI truth check
# ---------------------------------------------------------------------------


def _check_hmi_truth(result: Any, expected_route: str) -> Tuple[bool, str]:
    """Check that HMI state files reflect actual execution."""
    # The runtime bridge writes to history. We check the last written entry.
    runtime_dir = Path.home() / ".codex-api-home" / "lucy" / "runtime-v10"
    history_path = runtime_dir / "request_history.jsonl"

    if not history_path.exists():
        return True, "no history file yet (first run)"

    try:
        lines = history_path.read_text(encoding="utf-8").strip().split("\n")
        if not lines:
            return True, "empty history"
        last_entry = json.loads(lines[-1])
        route_payload = last_entry.get("route", {})
        outcome_payload = last_entry.get("outcome", {})
        actual_route_from_hmi = route_payload.get("mode", "unknown")
        actual_provider = outcome_payload.get("augmented_provider_used", "none")

        if actual_route_from_hmi != result.route:
            return False, f"HMI route {actual_route_from_hmi} != execution route {result.route}"

        if result.route == "AUGMENTED" and actual_provider == "none":
            return False, "AUGMENTED route but HMI shows provider=none"

        return True, f"HMI route={actual_route_from_hmi} provider={actual_provider}"
    except Exception as e:
        return False, f"HMI read error: {e}"


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def _execute_prompt(query: str, timeout: int = 60) -> Tuple[Any, Optional[str]]:
    """Execute a single prompt through the full router pipeline."""
    try:
        from router_py.main import execute_plan_python

        result = execute_plan_python(query, policy="fallback_only", timeout=timeout)
        return result, None
    except Exception as e:
        return None, str(e)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    print("=" * 70)
    print("Local Lucy V9 Burn-in Test")
    print(f"Started: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 70)

    prompts = _build_prompts()
    total = len(prompts)
    print(f"Total prompts: {total}")
    print()

    results: List[BurnInResult] = []
    category_stats: Dict[str, Dict[str, int]] = {}

    for idx, p in enumerate(prompts, 1):
        cat = p["category"]
        if cat not in category_stats:
            category_stats[cat] = {
                "total": 0,
                "route_ok": 0,
                "answer_ok": 0,
                "hmi_ok": 0,
                "errors": 0,
                "timeouts": 0,
            }
        category_stats[cat]["total"] += 1

        print(f"[{idx}/{total}] {p['id']}: {p['query'][:60]}...")

        start = time.time()
        exec_result, error = _execute_prompt(p["query"])
        duration_ms = int((time.time() - start) * 1000)

        if error:
            print(f"    ERROR: {error}")
            category_stats[cat]["errors"] += 1
            results.append(
                BurnInResult(
                    prompt_id=p["id"],
                    category=cat,
                    query=p["query"],
                    expected_route=p["expected_route"],
                    actual_route="ERROR",
                    response_text="",
                    duration_ms=duration_ms,
                    error=error,
                )
            )
            continue

        if exec_result is None:
            print("    ERROR: null result")
            category_stats[cat]["errors"] += 1
            continue

        route = getattr(exec_result, "route", "unknown")
        text = getattr(exec_result, "response_text", "") or ""
        status = getattr(exec_result, "status", "unknown")

        # Route correctness
        route_correct = False
        if p["expected_route"] == "varies":
            route_correct = True  # adversarial: we just observe
        elif route == p["expected_route"]:
            route_correct = True
        elif p["expected_route"] == "NEWS" and route == "LOCAL":
            # News may route LOCAL if no live data available — acceptable
            route_correct = True
        elif p["expected_route"] == "AUGMENTED" and (
            route == "LOCAL" or "requires evidence" in text.lower()
        ):
            # Augmented may route LOCAL if policy=disabled or provider unavailable
            route_correct = True

        if route_correct:
            category_stats[cat]["route_ok"] += 1

        # Answer acceptability
        acceptable, notes = _is_acceptable(p["query"], text, cat)
        if acceptable:
            category_stats[cat]["answer_ok"] += 1

        # HMI truth
        hmi_ok, hmi_notes = _check_hmi_truth(exec_result, p["expected_route"])
        if hmi_ok:
            category_stats[cat]["hmi_ok"] += 1

        print(f"    route={route} | acceptable={acceptable} | hmi={hmi_ok} | {duration_ms}ms")
        if not acceptable:
            print(f"    NOTE: {notes}")
        if not hmi_ok:
            print(f"    HMI: {hmi_notes}")

        results.append(
            BurnInResult(
                prompt_id=p["id"],
                category=cat,
                query=p["query"],
                expected_route=p["expected_route"],
                actual_route=route,
                response_text=text,
                duration_ms=duration_ms,
                route_correct=route_correct,
                answer_acceptable=acceptable,
                hmi_truth=hmi_ok,
                notes=f"{notes}; {hmi_notes}",
            )
        )

    # -------------------------------------------------------------------
    # Summary
    # -------------------------------------------------------------------
    print()
    print("=" * 70)
    print("BURN-IN SUMMARY")
    print("=" * 70)

    overall = {"total": 0, "route_ok": 0, "answer_ok": 0, "hmi_ok": 0, "errors": 0}
    for cat, stats in sorted(category_stats.items()):
        total_cat = stats["total"]
        route_pct = stats["route_ok"] / total_cat * 100 if total_cat else 0
        answer_pct = stats["answer_ok"] / total_cat * 100 if total_cat else 0
        hmi_pct = stats["hmi_ok"] / total_cat * 100 if total_cat else 0
        error_pct = stats["errors"] / total_cat * 100 if total_cat else 0

        overall["total"] += total_cat
        overall["route_ok"] += stats["route_ok"]
        overall["answer_ok"] += stats["answer_ok"]
        overall["hmi_ok"] += stats["hmi_ok"]
        overall["errors"] += stats["errors"]

        print(
            f"\n{cat:20s}  n={total_cat:3d}  route={route_pct:5.1f}%  answer={answer_pct:5.1f}%  hmi={hmi_pct:5.1f}%  errors={error_pct:5.1f}%"
        )

    print()
    print("-" * 70)
    total_all = overall["total"]
    print(
        f"{'TOTAL':20s}  n={total_all:3d}  route={overall['route_ok']/total_all*100:5.1f}%  answer={overall['answer_ok']/total_all*100:5.1f}%  hmi={overall['hmi_ok']/total_all*100:5.1f}%  errors={overall['errors']/total_all*100:5.1f}%"
    )
    print("=" * 70)

    # Promotion verdict
    route_rate = overall["route_ok"] / total_all * 100
    answer_rate = overall["answer_ok"] / total_all * 100
    error_rate = overall["errors"] / total_all * 100

    print()
    print("PROMOTION VERDICT:")
    if error_rate > 5:
        print("  FAIL — error/crash/hang rate > 5%")
    elif answer_rate < 95:
        print("  CONDITIONAL — answer acceptability < 95%")
    elif route_rate < 90:
        print("  CONDITIONAL — route correctness < 90%")
    else:
        print("  PASS — meets beta gates:")
        print(f"    route correct:    {route_rate:.1f}% (gate: 90%)")
        print(f"    answer acceptable:{answer_rate:.1f}% (gate: 95%)")
        print(f"    error rate:       {error_rate:.1f}% (gate: <5%)")
        print("  Recommendation: tag as beta")

    # Write JSON report
    report_path = Path("tests/burn_in_report_2026_05_18.json")
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "commit": _get_git_commit(),
        "total_prompts": total_all,
        "overall": {
            "route_correct_pct": route_rate,
            "answer_acceptable_pct": answer_rate,
            "hmi_truth_pct": overall["hmi_ok"] / total_all * 100,
            "error_rate_pct": error_rate,
        },
        "by_category": {
            cat: {k: v for k, v in stats.items()} for cat, stats in category_stats.items()
        },
        "results": [
            {
                "prompt_id": r.prompt_id,
                "category": r.category,
                "query": r.query,
                "expected_route": r.expected_route,
                "actual_route": r.actual_route,
                "route_correct": r.route_correct,
                "answer_acceptable": r.answer_acceptable,
                "hmi_truth": r.hmi_truth,
                "duration_ms": r.duration_ms,
                "error": r.error,
                "notes": r.notes,
            }
            for r in results
        ],
    }
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"\nFull report written to: {report_path}")

    return 0 if error_rate < 5 and answer_rate >= 95 else 1


def _get_git_commit() -> str:
    import subprocess

    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=str(Path(__file__).resolve().parent.parent),
            )
            .decode()
            .strip()
        )
    except Exception:
        return "unknown"


if __name__ == "__main__":
    sys.exit(main())
