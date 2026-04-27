#!/usr/bin/env python3
"""
Extended Shadow Testing Runner

Runs comprehensive shadow testing with the full query corpus.
Generates detailed reports with statistics and categorization.

Usage:
    python3 extended_shadow_runner.py
    python3 extended_shadow_runner.py --quick  # Run subset
    python3 extended_shadow_runner.py --report-only  # Analyze existing results
"""

import argparse
import json
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

# Import corpus
from shadow_corpus import get_all_queries

# Add parent to path
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR / "tools"))

from router_py.main import execute_plan_shadow, RouterOutcome, ShadowComparison


@dataclass
class CategoryStats:
    """Statistics for a query category."""
    total: int = 0
    true_parity: int = 0
    intended_improvement: int = 0
    suspicious_drift: int = 0
    hard_regression: int = 0
    errors: int = 0
    avg_shell_time_ms: float = 0.0
    avg_python_time_ms: float = 0.0
    avg_speedup: float = 0.0


@dataclass
class ExtendedReport:
    """Comprehensive shadow testing report."""
    timestamp: str
    total_queries: int
    queries_by_classification: dict[str, int]
    queries_by_category: dict[str, CategoryStats]
    performance_summary: dict[str, Any]
    suspicious_cases: list[dict]
    regression_cases: list[dict]
    errors: list[dict]
    raw_results: list[ShadowComparison] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "total_queries": self.total_queries,
            "summary": {
                "true_parity": self.queries_by_classification.get("true_parity", 0),
                "intended_improvement": self.queries_by_classification.get("intended_improvement", 0),
                "suspicious_drift": self.queries_by_classification.get("suspicious_drift", 0),
                "hard_regression": self.queries_by_classification.get("hard_regression", 0),
            },
            "categories": {
                cat: {
                    "total": stats.total,
                    "true_parity": stats.true_parity,
                    "intended_improvement": stats.intended_improvement,
                    "suspicious_drift": stats.suspicious_drift,
                    "hard_regression": stats.hard_regression,
                    "errors": stats.errors,
                    "avg_speedup": round(stats.avg_speedup, 2),
                }
                for cat, stats in self.queries_by_category.items()
            },
            "performance": self.performance_summary,
            "suspicious_cases": self.suspicious_cases[:10],  # Top 10
            "regression_cases": self.regression_cases[:10],  # Top 10
        }


def run_extended_shadow_tests(
    queries: list[tuple[str, str]],
    timeout: int = 30,
    progress_interval: int = 10,
) -> list[ShadowComparison]:
    """Run shadow tests for all queries."""
    results = []
    total = len(queries)
    
    print(f"Running extended shadow tests: {total} queries")
    print(f"Timeout per query: {timeout}s")
    print("=" * 60)
    
    start_time = time.time()
    
    for i, (query, category) in enumerate(queries, 1):
        if i % progress_interval == 0 or i == 1:
            elapsed = time.time() - start_time
            rate = i / elapsed if elapsed > 0 else 0
            eta = (total - i) / rate if rate > 0 else 0
            print(f"[{i}/{total}] {query[:50]:<50} (ETA: {eta/60:.1f}m)")
        
        try:
            # Clear old shadow logs
            log_dir = ROOT_DIR / "logs" / "router_py_shadow"
            if log_dir.exists():
                for f in log_dir.glob("shadow_diff_*.json"):
                    f.unlink()
            
            # Run shadow mode
            result = execute_plan_shadow(query, timeout=timeout)
            
            # Find the shadow comparison log
            comparison = None
            if log_dir.exists():
                log_files = sorted(log_dir.glob("shadow_diff_*.json"), 
                                  key=lambda p: p.stat().st_mtime, reverse=True)
                if log_files:
                    with open(log_files[0]) as f:
                        data = json.load(f)
                        comparison = ShadowComparison(
                            query=data["query"],
                            shell_result=_dict_to_outcome(data.get("shell")),
                            python_result=_dict_to_outcome(data.get("python")),
                            match=data.get("match", False),
                            differences=data.get("differences", []),
                            timestamp=data.get("timestamp", ""),
                            classification=data.get("classification", "unknown"),
                        )
            
            if comparison:
                results.append(comparison)
            else:
                # Create synthetic result if no log found
                results.append(ShadowComparison(
                    query=query,
                    shell_result=None,
                    python_result=None,
                    match=False,
                    differences=["ERROR: No shadow log found"],
                    classification="error",
                ))
                
        except Exception as e:
            results.append(ShadowComparison(
                query=query,
                shell_result=None,
                python_result=None,
                match=False,
                differences=[f"ERROR: {str(e)}"],
                classification="error",
            ))
    
    total_time = time.time() - start_time
    print(f"\nCompleted {len(results)} queries in {total_time/60:.1f} minutes")
    print(f"Average: {total_time/len(results):.1f}s per query")
    
    return results


def _dict_to_outcome(data: dict | None) -> RouterOutcome | None:
    """Convert dict to RouterOutcome."""
    if not data:
        return None
    return RouterOutcome(
        status=data.get("status", "unknown"),
        outcome_code=data.get("outcome_code", "unknown"),
        route=data.get("route", "unknown"),
        provider=data.get("provider", "unknown"),
        provider_usage_class=data.get("provider_usage_class", "unknown"),
        intent_family=data.get("intent_family", "unknown"),
        confidence=data.get("confidence", 0.0),
        response_text=data.get("response_text", ""),
        error_message=data.get("error_message", ""),
        execution_time_ms=data.get("execution_time_ms", 0),
        request_id=data.get("request_id", ""),
    )


def analyze_results(
    comparisons: list[ShadowComparison],
    queries: list[tuple[str, str]],
) -> ExtendedReport:
    """Analyze shadow test results and generate report."""
    
    # Build category lookup
    query_to_category = {q: cat for q, cat in queries}
    
    # Initialize counters
    by_classification = defaultdict(int)
    by_category = defaultdict(CategoryStats)
    
    suspicious_cases = []
    regression_cases = []
    errors = []
    
    total_shell_time = 0
    total_python_time = 0
    total_speedup = 0
    valid_count = 0
    
    for comp in comparisons:
        cat = query_to_category.get(comp.query, "unknown")
        
        # Update classification counts
        by_classification[comp.classification] += 1
        
        # Update category stats
        stats = by_category[cat]
        stats.total += 1
        
        if comp.classification == "true_parity":
            stats.true_parity += 1
        elif comp.classification == "intended_improvement":
            stats.intended_improvement += 1
        elif comp.classification == "suspicious_drift":
            stats.suspicious_drift += 1
            suspicious_cases.append({
                "query": comp.query,
                "category": cat,
                "differences": comp.differences,
                "shell": comp.shell_result.to_dict() if comp.shell_result else None,
                "python": comp.python_result.to_dict() if comp.python_result else None,
            })
        elif comp.classification == "hard_regression":
            stats.hard_regression += 1
            regression_cases.append({
                "query": comp.query,
                "category": cat,
                "differences": comp.differences,
                "shell": comp.shell_result.to_dict() if comp.shell_result else None,
                "python": comp.python_result.to_dict() if comp.python_result else None,
            })
        elif comp.classification == "error":
            stats.errors += 1
            errors.append({
                "query": comp.query,
                "category": cat,
                "error": comp.differences[0] if comp.differences else "Unknown",
            })
        
        # Update performance stats
        if comp.shell_result and comp.python_result:
            stats.avg_shell_time_ms += comp.shell_result.execution_time_ms
            stats.avg_python_time_ms += comp.python_result.execution_time_ms
            if comp.python_result.execution_time_ms > 0:
                speedup = comp.shell_result.execution_time_ms / comp.python_result.execution_time_ms
                stats.avg_speedup += speedup
            valid_count += 1
    
    # Calculate averages
    for stats in by_category.values():
        if stats.total > 0:
            stats.avg_shell_time_ms /= stats.total
            stats.avg_python_time_ms /= stats.total
            stats.avg_speedup /= stats.total
    
    # Overall performance
    perf_summary = {
        "avg_shell_time_ms": sum(s.avg_shell_time_ms for s in by_category.values()) / len(by_category) if by_category else 0,
        "avg_python_time_ms": sum(s.avg_python_time_ms for s in by_category.values()) / len(by_category) if by_category else 0,
        "avg_speedup": sum(s.avg_speedup for s in by_category.values()) / len(by_category) if by_category else 0,
    }
    
    return ExtendedReport(
        timestamp=datetime.now().isoformat(),
        total_queries=len(comparisons),
        queries_by_classification=dict(by_classification),
        queries_by_category=dict(by_category),
        performance_summary=perf_summary,
        suspicious_cases=suspicious_cases,
        regression_cases=regression_cases,
        errors=errors,
        raw_results=comparisons,
    )


def print_extended_report(report: ExtendedReport):
    """Print comprehensive report."""
    print("\n" + "=" * 70)
    print("EXTENDED SHADOW TESTING REPORT")
    print("=" * 70)
    print(f"Timestamp: {report.timestamp}")
    print(f"Total Queries: {report.total_queries}")
    
    # Classification summary
    print("\n" + "-" * 70)
    print("CLASSIFICATION SUMMARY")
    print("-" * 70)
    
    summary = report.queries_by_classification
    total = report.total_queries
    
    print(f"  ✅ True Parity:           {summary.get('true_parity', 0):>4} ({100*summary.get('true_parity', 0)/total:5.1f}%)")
    print(f"  ⬆️  Intended Improvement:  {summary.get('intended_improvement', 0):>4} ({100*summary.get('intended_improvement', 0)/total:5.1f}%)")
    print(f"  ⚠️  Suspicious Drift:      {summary.get('suspicious_drift', 0):>4} ({100*summary.get('suspicious_drift', 0)/total:5.1f}%)")
    print(f"  ❌ Hard Regression:       {summary.get('hard_regression', 0):>4} ({100*summary.get('hard_regression', 0)/total:5.1f}%)")
    print(f"  💥 Errors:                {summary.get('error', 0):>4} ({100*summary.get('error', 0)/total:5.1f}%)")
    
    # Performance
    print("\n" + "-" * 70)
    print("PERFORMANCE SUMMARY")
    print("-" * 70)
    perf = report.performance_summary
    print(f"  Avg Shell Time:   {perf['avg_shell_time_ms']:>6.0f} ms")
    print(f"  Avg Python Time:  {perf['avg_python_time_ms']:>6.0f} ms")
    print(f"  Avg Speedup:      {perf['avg_speedup']:>6.1f}x")
    
    # Category breakdown
    print("\n" + "-" * 70)
    print("CATEGORY BREAKDOWN")
    print("-" * 70)
    print(f"{'Category':<25} {'Total':>6} {'Parity':>6} {'Imprv':>6} {'Drift':>6} {'Regrs':>6} {'Speedup':>8}")
    print("-" * 70)
    
    for cat in sorted(report.queries_by_category.keys()):
        stats = report.queries_by_category[cat]
        print(f"{cat:<25} {stats.total:>6} {stats.true_parity:>6} "
              f"{stats.intended_improvement:>6} {stats.suspicious_drift:>6} "
              f"{stats.hard_regression:>6} {stats.avg_speedup:>7.1f}x")
    
    # Issues
    if report.suspicious_cases:
        print("\n" + "-" * 70)
        print(f"SUSPICIOUS DRIFT CASES ({len(report.suspicious_cases)} total)")
        print("-" * 70)
        for i, case in enumerate(report.suspicious_cases[:5], 1):
            print(f"\n{i}. [{case['category']}] {case['query'][:60]}")
            print(f"   Differences: {', '.join(case['differences'])}")
    
    if report.regression_cases:
        print("\n" + "-" * 70)
        print(f"HARD REGRESSION CASES ({len(report.regression_cases)} total)")
        print("-" * 70)
        for i, case in enumerate(report.regression_cases[:5], 1):
            print(f"\n{i}. [{case['category']}] {case['query'][:60]}")
            print(f"   Differences: {', '.join(case['differences'])}")
    
    if report.errors:
        print("\n" + "-" * 70)
        print(f"ERRORS ({len(report.errors)} total)")
        print("-" * 70)
        for i, err in enumerate(report.errors[:5], 1):
            print(f"{i}. [{err['category']}] {err['query'][:50]}: {err['error'][:50]}")
    
    # Conclusion
    print("\n" + "=" * 70)
    print("CONCLUSION")
    print("=" * 70)
    
    parity_rate = summary.get('true_parity', 0) / total
    improvement_rate = summary.get('intended_improvement', 0) / total
    drift_rate = summary.get('suspicious_drift', 0) / total
    regression_rate = summary.get('hard_regression', 0) / total
    
    effective_parity = parity_rate + improvement_rate
    
    if effective_parity >= 0.95 and drift_rate == 0 and regression_rate == 0:
        print("✅ EXCELLENT: Python router is ready for production!")
        print(f"   Effective parity: {100*effective_parity:.1f}%")
    elif effective_parity >= 0.85 and drift_rate < 0.05 and regression_rate == 0:
        print("✅ GOOD: Python router is likely safe for gradual rollout")
        print(f"   Effective parity: {100*effective_parity:.1f}%")
        print(f"   Review {len(report.suspicious_cases)} suspicious drift cases")
    elif drift_rate > 0.05 or regression_rate > 0:
        print("⚠️  NEEDS ATTENTION: Significant drift or regressions detected")
        print(f"   Suspicious drift: {100*drift_rate:.1f}%")
        print(f"   Hard regressions: {100*regression_rate:.1f}%")
    else:
        print("❌ NOT READY: Too many unexplained differences")
        print(f"   Effective parity: {100*effective_parity:.1f}%")
    
    print("=" * 70)


def save_report(report: ExtendedReport, output_dir: Path | None = None):
    """Save report to JSON file."""
    if output_dir is None:
        output_dir = ROOT_DIR / "logs" / "router_py_shadow"
    
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = output_dir / f"extended_shadow_report_{timestamp}.json"
    
    with open(output_file, "w") as f:
        json.dump(report.to_dict(), f, indent=2)
    
    print(f"\nReport saved to: {output_file}")
    return output_file


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Extended Shadow Testing Runner")
    parser.add_argument("--quick", action="store_true", help="Run quick subset (20 queries)")
    parser.add_argument("--timeout", type=int, default=30, help="Timeout per query")
    parser.add_argument("--save", action="store_true", help="Save results to file")
    args = parser.parse_args()
    
    # Get queries
    all_queries = get_all_queries()
    
    if args.quick:
        # Take first 20 queries, evenly distributed across categories
        queries = all_queries[:20]
        print(f"QUICK MODE: Running {len(queries)} queries")
    else:
        queries = all_queries
        print(f"FULL MODE: Running {len(queries)} queries")
    
    # Run tests
    start_time = time.time()
    comparisons = run_extended_shadow_tests(queries, timeout=args.timeout)
    elapsed = time.time() - start_time
    
    # Analyze
    report = analyze_results(comparisons, queries)
    
    # Print
    print_extended_report(report)
    
    # Save
    if args.save:
        save_report(report)
    
    print(f"\nTotal time: {elapsed/60:.1f} minutes")
    
    # Exit code based on results
    summary = report.queries_by_classification
    total = report.total_queries
    
    drift_rate = summary.get('suspicious_drift', 0) / total
    regression_rate = summary.get('hard_regression', 0) / total
    
    if regression_rate > 0:
        return 2  # Hard regressions found
    elif drift_rate > 0.05:
        return 1  # Significant drift
    else:
        return 0  # Good results


if __name__ == "__main__":
    sys.exit(main())
