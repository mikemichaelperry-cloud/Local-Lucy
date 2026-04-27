#!/usr/bin/env python3
"""
Shadow Mode Test Suite - Validate Python router accuracy vs shell.

Runs a comprehensive set of queries through both implementations,
compares results, and generates a validation report.
"""

import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Test queries covering different intent families and routing scenarios
TEST_QUERIES = [
    # Local answer queries (math, simple facts)
    ("What is 2+2?", "local_math"),
    ("What is the capital of France?", "local_fact"),
    ("How many days in a week?", "local_simple"),
    
    # Background overview queries (should route to Wikipedia)
    ("Who was Ada Lovelace?", "background_biography"),
    ("Tell me about the Roman Empire", "background_history"),
    ("What is the history of the Internet?", "background_tech"),
    ("Who was Marie Curie?", "background_science"),
    
    # Current evidence queries (should route to paid provider)
    ("What is the latest news about Ukraine?", "current_news"),
    ("Breaking news today", "current_breaking"),
    
    # Medical queries (should trigger evidence mode)
    ("What are the symptoms of flu?", "medical_symptoms"),
    ("How to treat a headache?", "medical_treatment"),
    
    # Synthesis queries
    ("Explain quantum mechanics simply", "synthesis_explain"),
    ("Compare capitalism and socialism", "synthesis_compare"),
    
    # Clarification needed (ambiguous)
    ("Tell me about it", "clarify_vague"),
    ("What do you think?", "clarify_subjective"),
    
    # Edge cases
    ("", "edge_empty"),
    ("Hi", "edge_short"),
    ("a" * 500, "edge_long"),
    ("What's the weather?", "edge_contextual"),
]


@dataclass
class ShadowTestResult:
    """Result of a single shadow test."""
    query: str
    category: str
    match: bool
    shell_time_ms: int
    python_time_ms: int
    speedup: float
    differences: list[str]
    shell_route: str
    python_route: str
    shell_provider: str
    python_provider: str
    shell_intent: str
    python_intent: str
    error: Optional[str] = None


@dataclass
class ShadowReport:
    """Aggregated shadow test report."""
    timestamp: str
    total_tests: int
    matches: int
    mismatches: int
    errors: int
    avg_shell_time_ms: float
    avg_python_time_ms: float
    avg_speedup: float
    results: list[ShadowTestResult]
    mismatch_details: list[ShadowTestResult] = field(default_factory=list)


def run_shadow_mode(query: str, timeout: int = 30) -> Optional[dict]:
    """Run a query through shadow mode and return parsed result."""
    try:
        result = subprocess.run(
            ["./tools/router_py/hybrid_wrapper.sh", query],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(Path(__file__).resolve().parent.parent.parent),
            env={**dict(subprocess.os.environ), "LUCY_ROUTER_PY": "shadow"},
        )
        
        # Look for the most recent shadow log file
        log_dir = Path(__file__).resolve().parent.parent.parent / "logs" / "router_py_shadow"
        if log_dir.exists():
            log_files = sorted(log_dir.glob("shadow_diff_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
            if log_files:
                with open(log_files[0]) as f:
                    return json.load(f)
        
        return None
    except Exception as e:
        return {"error": str(e)}


def categorize_mismatch(diff: str) -> str:
    """Categorize a mismatch for reporting."""
    if "intent_family" in diff:
        return "intent_family"
    elif "route" in diff:
        return "route"
    elif "provider" in diff:
        return "provider"
    elif "status" in diff:
        return "status"
    elif "outcome_code" in diff:
        return "outcome_code"
    else:
        return "other"


def run_test_suite() -> ShadowReport:
    """Run the full shadow test suite."""
    print(f"Running Shadow Mode Test Suite")
    print(f"{'=' * 60}")
    print(f"Testing {len(TEST_QUERIES)} queries...\n")
    
    results = []
    mismatch_details = []
    
    for i, (query, category) in enumerate(TEST_QUERIES, 1):
        print(f"[{i}/{len(TEST_QUERIES)}] Testing: {query[:50]}{'...' if len(query) > 50 else ''} ({category})")
        
        # Clear old log files to ensure we get fresh results
        log_dir = Path(__file__).resolve().parent.parent.parent / "logs" / "router_py_shadow"
        if log_dir.exists():
            for f in log_dir.glob("shadow_diff_*.json"):
                f.unlink()
        
        # Run shadow mode
        start_time = time.time()
        shadow_result = run_shadow_mode(query)
        elapsed = int((time.time() - start_time) * 1000)
        
        if shadow_result is None or "error" in shadow_result:
            result = ShadowTestResult(
                query=query,
                category=category,
                match=False,
                shell_time_ms=0,
                python_time_ms=0,
                speedup=0.0,
                differences=["ERROR: Failed to get shadow result"],
                shell_route="ERROR",
                python_route="ERROR",
                shell_provider="ERROR",
                python_provider="ERROR",
                shell_intent="ERROR",
                python_intent="ERROR",
                error=shadow_result.get("error") if shadow_result else "No result",
            )
        else:
            shell = shadow_result.get("shell", {})
            python = shadow_result.get("python", {})
            
            shell_time = shell.get("execution_time_ms", 0) or elapsed // 2
            python_time = python.get("execution_time_ms", 0) or elapsed // 2
            speedup = shell_time / python_time if python_time > 0 else 1.0
            
            result = ShadowTestResult(
                query=query,
                category=category,
                match=shadow_result.get("match", False),
                shell_time_ms=shell_time,
                python_time_ms=python_time,
                speedup=speedup,
                differences=shadow_result.get("differences", []),
                shell_route=shell.get("route", "unknown"),
                python_route=python.get("route", "unknown"),
                shell_provider=shell.get("provider", "unknown"),
                python_provider=python.get("provider", "unknown"),
                shell_intent=shell.get("intent_family", "unknown"),
                python_intent=python.get("intent_family", "unknown"),
            )
        
        results.append(result)
        
        if not result.match:
            mismatch_details.append(result)
            print(f"  ⚠️  MISMATCH: {', '.join(result.differences)}")
        else:
            print(f"  ✅ MATCH (Python {result.speedup:.1f}x faster)")
    
    # Calculate aggregates
    total = len(results)
    matches = sum(1 for r in results if r.match and not r.error)
    errors = sum(1 for r in results if r.error)
    mismatches = total - matches - errors
    
    avg_shell = sum(r.shell_time_ms for r in results if not r.error) / max(1, total - errors)
    avg_python = sum(r.python_time_ms for r in results if not r.error) / max(1, total - errors)
    avg_speedup = sum(r.speedup for r in results if not r.error) / max(1, total - errors)
    
    return ShadowReport(
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        total_tests=total,
        matches=matches,
        mismatches=mismatches,
        errors=errors,
        avg_shell_time_ms=avg_shell,
        avg_python_time_ms=avg_python,
        avg_speedup=avg_speedup,
        results=results,
        mismatch_details=mismatch_details,
    )


def print_report(report: ShadowReport):
    """Print formatted report."""
    print(f"\n{'=' * 60}")
    print(f"SHADOW MODE VALIDATION REPORT")
    print(f"{'=' * 60}")
    print(f"Timestamp: {report.timestamp}")
    print(f"\nSummary:")
    print(f"  Total Tests:     {report.total_tests}")
    print(f"  Matches:         {report.matches} ({100*report.matches/report.total_tests:.1f}%)")
    print(f"  Mismatches:      {report.mismatches} ({100*report.mismatches/report.total_tests:.1f}%)")
    print(f"  Errors:          {report.errors} ({100*report.errors/report.total_tests:.1f}%)")
    print(f"\nPerformance:")
    print(f"  Avg Shell Time:  {report.avg_shell_time_ms:.0f} ms")
    print(f"  Avg Python Time: {report.avg_python_time_ms:.0f} ms")
    print(f"  Avg Speedup:     {report.avg_speedup:.1f}x faster")
    
    if report.mismatch_details:
        print(f"\n{'=' * 60}")
        print(f"MISMATCH DETAILS")
        print(f"{'=' * 60}")
        
        # Group by category
        by_category = {}
        for r in report.mismatch_details:
            cat = r.category
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(r)
        
        for category, results in sorted(by_category.items()):
            print(f"\n{category.upper()}:")
            for r in results:
                print(f"  Query: {r.query[:60]}{'...' if len(r.query) > 60 else ''}")
                print(f"    Differences: {', '.join(r.differences)}")
                print(f"    Shell:  route={r.shell_route}, provider={r.shell_provider}, intent={r.shell_intent}")
                print(f"    Python: route={r.python_route}, provider={r.python_provider}, intent={r.python_intent}")
    
    # Categorize mismatches
    if report.mismatches > 0:
        print(f"\n{'=' * 60}")
        print(f"MISMATCH CATEGORIES")
        print(f"{'=' * 60}")
        
        categories = {}
        for r in report.mismatch_details:
            for diff in r.differences:
                cat = categorize_mismatch(diff)
                categories[cat] = categories.get(cat, 0) + 1
        
        for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
            print(f"  {cat}: {count}")
    
    print(f"\n{'=' * 60}")
    print(f"CONCLUSION")
    print(f"{'=' * 60}")
    
    match_rate = 100 * report.matches / report.total_tests
    if match_rate >= 95:
        print(f"✅ EXCELLENT: {match_rate:.1f}% match rate. Python router is ready for production!")
    elif match_rate >= 85:
        print(f"⚠️  GOOD: {match_rate:.1f}% match rate. Minor differences to review.")
    elif match_rate >= 70:
        print(f"⚠️  FAIR: {match_rate:.1f}% match rate. Significant differences need attention.")
    else:
        print(f"❌ POOR: {match_rate:.1f}% match rate. Major discrepancies - not ready for production.")
    
    print(f"\nSpeedup: {report.avg_speedup:.1f}x average")
    if report.avg_speedup >= 5:
        print(f"🚀 EXCEPTIONAL performance improvement!")
    elif report.avg_speedup >= 2:
        print(f"✅ GOOD performance improvement")
    else:
        print(f"⚠️  Modest performance improvement")


def save_report(report: ShadowReport, filename: Optional[str] = None):
    """Save report to JSON file."""
    if filename is None:
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = f"shadow_report_{timestamp}.json"
    
    output_dir = Path(__file__).resolve().parent.parent.parent / "logs" / "router_py_shadow"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / filename
    
    # Convert to dict
    report_dict = {
        "timestamp": report.timestamp,
        "summary": {
            "total_tests": report.total_tests,
            "matches": report.matches,
            "mismatches": report.mismatches,
            "errors": report.errors,
            "match_rate": report.matches / report.total_tests,
        },
        "performance": {
            "avg_shell_time_ms": report.avg_shell_time_ms,
            "avg_python_time_ms": report.avg_python_time_ms,
            "avg_speedup": report.avg_speedup,
        },
        "results": [
            {
                "query": r.query,
                "category": r.category,
                "match": r.match,
                "shell_time_ms": r.shell_time_ms,
                "python_time_ms": r.python_time_ms,
                "speedup": r.speedup,
                "differences": r.differences,
                "shell_route": r.shell_route,
                "python_route": r.python_route,
                "shell_provider": r.shell_provider,
                "python_provider": r.python_provider,
                "shell_intent": r.shell_intent,
                "python_intent": r.python_intent,
                "error": r.error,
            }
            for r in report.results
        ],
    }
    
    with open(output_path, "w") as f:
        json.dump(report_dict, f, indent=2)
    
    print(f"\nReport saved to: {output_path}")


def main():
    """Run the shadow test suite."""
    print("Local Lucy Router - Shadow Mode Validation Suite")
    print(f"{'=' * 60}\n")
    
    start_time = time.time()
    report = run_test_suite()
    elapsed = time.time() - start_time
    
    print_report(report)
    save_report(report)
    
    print(f"\nTotal time: {elapsed:.1f}s")
    
    return 0 if report.matches / report.total_tests >= 0.85 else 1


if __name__ == "__main__":
    sys.exit(main())
