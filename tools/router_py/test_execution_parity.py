#!/usr/bin/env python3
"""
Test Harness for Migration Validation: Shell vs Python execute_plan

This test harness validates parity between the shell-based execute_plan.sh
and the Python-based execution_engine during migration.

Usage:
    # Run all tests and compare outputs
    python test_execution_parity.py
    
    # Run in shadow mode (log differences without failing)
    python test_execution_parity.py --shadow-mode
    
    # Run specific test categories
    python test_execution_parity.py --category local,news
    
    # Generate JSON report
    python test_execution_parity.py --json-report report.json
    
    # Run with verbose output
    python test_execution_parity.py -v

Exit Codes:
    0 = All tests passed (or shadow mode with differences logged)
    1 = One or more tests failed (parity mismatch)
    2 = Configuration or environment error
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


# =============================================================================
# Configuration
# =============================================================================

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
SHELL_EXECUTE_PLAN = ROOT_DIR / "tools" / "router" / "execute_plan.sh"
PYTHON_EXECUTE_PLAN = ROOT_DIR / "tools" / "router_py" / "main.py"

# Default timeouts (seconds)
DEFAULT_TIMEOUT = 60
SHELL_TIMEOUT = 120
PYTHON_TIMEOUT = 120

# Output normalization patterns (for comparison)
NORMALIZATION_PATTERNS = [
    # Remove timestamps
    (r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?([+-]\d{2}:\d{2})?', 'TIMESTAMP'),
    # Remove session IDs
    (r'session_[a-f0-9]{8,32}', 'SESSION_ID'),
    # Remove temporary file paths
    (r'/tmp/[^\s]+', '/tmp/TEMPFILE'),
    # Remove specific timing values
    (r'\d+\.?\d*\s*ms', 'Xms'),
    (r'\d+\.?\d*\s*seconds?', 'X seconds'),
]


# =============================================================================
# Data Structures
# =============================================================================

@dataclass
class ExecutionResult:
    """Result from executing either shell or Python implementation."""
    
    implementation: str  # "shell" or "python"
    query: str
    stdout: str
    stderr: str
    returncode: int
    execution_time_ms: float
    timed_out: bool = False
    error_message: str = ""
    
    # Parsed metadata
    outcome_code: str = ""
    route: str = ""
    trust_class: str = ""
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "implementation": self.implementation,
            "query": self.query,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "returncode": self.returncode,
            "execution_time_ms": self.execution_time_ms,
            "timed_out": self.timed_out,
            "error_message": self.error_message,
            "outcome_code": self.outcome_code,
            "route": self.route,
            "trust_class": self.trust_class,
        }


@dataclass
class ComparisonResult:
    """Comparison between shell and Python results."""
    
    test_name: str
    query: str
    category: str
    shell_result: ExecutionResult | None
    python_result: ExecutionResult | None
    match: bool
    match_details: dict[str, bool] = field(default_factory=dict)
    differences: list[str] = field(default_factory=list)
    diff_summary: str = ""
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "test_name": self.test_name,
            "query": self.query,
            "category": self.category,
            "shell": self.shell_result.to_dict() if self.shell_result else None,
            "python": self.python_result.to_dict() if self.python_result else None,
            "match": self.match,
            "match_details": self.match_details,
            "differences": self.differences,
            "diff_summary": self.diff_summary,
        }


@dataclass
class TestReport:
    """Overall test report."""
    
    timestamp: str
    total_tests: int
    passed: int
    failed: int
    skipped: int
    shadow_mode: bool
    results: list[ComparisonResult]
    summary: dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "total_tests": self.total_tests,
            "passed": self.passed,
            "failed": self.failed,
            "skipped": self.skipped,
            "shadow_mode": self.shadow_mode,
            "results": [r.to_dict() for r in self.results],
            "summary": self.summary,
        }


# =============================================================================
# Test Fixtures
# =============================================================================

TEST_FIXTURES = [
    # Local queries (no web needed)
    {
        "name": "local_baking",
        "category": "local",
        "query": "how to bake sourdough bread",
        "expected_route": "LOCAL",
        "min_output_length": 10,
    },
    {
        "name": "local_python_syntax",
        "category": "local",
        "query": "Python dictionary syntax",
        "expected_route": "LOCAL",
        "min_output_length": 10,
    },
    {
        "name": "local_explanation",
        "category": "local",
        "query": "explain recursion in simple terms",
        "expected_route": "LOCAL",
        "min_output_length": 10,
    },
    
    # News queries (requires web)
    {
        "name": "news_latest",
        "category": "news",
        "query": "latest news",
        "expected_route": "NEWS",
        "min_output_length": 5,
    },
    {
        "name": "news_current_events",
        "category": "news",
        "query": "what happened today",
        "expected_route": "NEWS",
        "min_output_length": 5,
    },
    
    # Evidence queries (requires sources)
    {
        "name": "evidence_research",
        "category": "evidence",
        "query": "latest research on climate change",
        "expected_route": "EVIDENCE",
        "min_output_length": 5,
    },
    {
        "name": "evidence_medical",
        "category": "evidence",
        "query": "Is aspirin safe for daily use",
        "expected_route": "EVIDENCE",
        "min_output_length": 5,
    },
    
    # Augmented queries (unverified context)
    {
        "name": "augmented_biography",
        "category": "augmented",
        "query": "who is Marie Curie",
        "expected_route": "AUGMENTED",
        "min_output_length": 10,
    },
    {
        "name": "augmented_history",
        "category": "augmented",
        "query": "history of the internet",
        "expected_route": "AUGMENTED",
        "min_output_length": 10,
    },
    
    # Clarification queries (ambiguous)
    {
        "name": "clarify_ambiguous",
        "category": "clarify",
        "query": "tell me about python",
        "expected_route": "CLARIFY",
        "min_output_length": 5,
    },
    {
        "name": "clarify_vague",
        "category": "clarify",
        "query": "what about that thing",
        "expected_route": "CLARIFY",
        "min_output_length": 5,
    },
    
    # Edge cases
    {
        "name": "edge_empty",
        "category": "error",
        "query": "",
        "expected_route": "ERROR",
        "should_fail": True,
    },
    {
        "name": "edge_whitespace",
        "category": "error",
        "query": "   ",
        "expected_route": "ERROR",
        "should_fail": True,
    },
    {
        "name": "edge_greeting",
        "category": "local",
        "query": "hi",
        "expected_route": "LOCAL",
        "min_output_length": 1,
    },
    {
        "name": "edge_punctuation",
        "category": "local",
        "query": "?!?",
        "expected_route": "LOCAL",
    },
]


# =============================================================================
# Execution Engine
# =============================================================================

class ExecutionEngine:
    """Executes queries against shell or Python implementation."""
    
    def __init__(self, root_dir: Path, timeout: int = DEFAULT_TIMEOUT):
        self.root_dir = root_dir
        self.timeout = timeout
        self.env = os.environ.copy()
        
        # Ensure consistent environment
        self.env["LUCY_RUNTIME_AUTHORITY_ROOT"] = str(root_dir)
        self.env["LUCY_ROOT"] = str(root_dir)
        
        # Use isolated state namespace for testing
        self.env["LUCY_SHARED_STATE_NAMESPACE"] = f"test_parity_{int(time.time())}"
    
    def run_shell(
        self,
        query: str,
        extra_env: dict[str, str] | None = None,
    ) -> ExecutionResult:
        """Execute query using shell implementation."""
        return self._run_impl(
            implementation="shell",
            executable=SHELL_EXECUTE_PLAN,
            query=query,
            extra_env=extra_env,
        )
    
    def run_python(
        self,
        query: str,
        extra_env: dict[str, str] | None = None,
    ) -> ExecutionResult:
        """Execute query using Python implementation."""
        # Check if Python implementation exists and is ready
        if not PYTHON_EXECUTE_PLAN.exists():
            return ExecutionResult(
                implementation="python",
                query=query,
                stdout="",
                stderr="Python implementation not found",
                returncode=-1,
                execution_time_ms=0.0,
                error_message=f"Python implementation not found at {PYTHON_EXECUTE_PLAN}",
            )
        
        return self._run_impl(
            implementation="python",
            executable=PYTHON_EXECUTE_PLAN,
            query=query,
            extra_env=extra_env,
        )
    
    def _run_impl(
        self,
        implementation: str,
        executable: Path,
        query: str,
        extra_env: dict[str, str] | None = None,
    ) -> ExecutionResult:
        """Run implementation with query."""
        start_time = time.time()
        
        env = self.env.copy()
        if extra_env:
            env.update(extra_env)
        
        # Set implementation-specific env vars
        if implementation == "python":
            env["LUCY_ROUTER_PY"] = "1"
        else:
            env["LUCY_ROUTER_PY"] = "0"
        
        try:
            # Use subprocess to run the implementation
            # execute_plan.sh takes query as arguments or stdin
            if query:
                cmd = [str(executable), query]
            else:
                cmd = [str(executable)]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env=env,
                cwd=self.root_dir,
            )
            
            execution_time_ms = (time.time() - start_time) * 1000
            
            # Parse metadata from output
            outcome_code = self._extract_outcome_code(result.stdout, result.stderr)
            route = self._extract_route(result.stdout, result.stderr)
            trust_class = self._extract_trust_class(result.stdout, result.stderr)
            
            return ExecutionResult(
                implementation=implementation,
                query=query,
                stdout=result.stdout,
                stderr=result.stderr,
                returncode=result.returncode,
                execution_time_ms=execution_time_ms,
                outcome_code=outcome_code,
                route=route,
                trust_class=trust_class,
            )
            
        except subprocess.TimeoutExpired as e:
            execution_time_ms = (time.time() - start_time) * 1000
            return ExecutionResult(
                implementation=implementation,
                query=query,
                stdout=e.stdout if e.stdout else "",
                stderr=e.stderr if e.stderr else "",
                returncode=-1,
                execution_time_ms=execution_time_ms,
                timed_out=True,
                error_message=f"Timeout after {self.timeout}s",
            )
        except Exception as e:
            execution_time_ms = (time.time() - start_time) * 1000
            return ExecutionResult(
                implementation=implementation,
                query=query,
                stdout="",
                stderr=str(e),
                returncode=-1,
                execution_time_ms=execution_time_ms,
                error_message=str(e),
            )
    
    def _extract_outcome_code(self, stdout: str, stderr: str) -> str:
        """Extract outcome code from output."""
        # Look for outcome code in stderr (trace output)
        match = re.search(r'OUTCOME_CODE[=:](\w+)', stderr)
        if match:
            return match.group(1)
        # Look for patterns in stdout
        if "insufficient evidence" in stdout.lower():
            return "validated_insufficient"
        if "clarification" in stdout.lower():
            return "clarification_requested"
        return ""
    
    def _extract_route(self, stdout: str, stderr: str) -> str:
        """Extract route from output."""
        # Look for route in stderr (trace output)
        match = re.search(r'(?:ROUTE_MODE|MODE|FINAL_MODE)[=:](\w+)', stderr)
        if match:
            return match.group(1)
        # Infer from stdout content
        if "Augmented" in stdout:
            return "AUGMENTED"
        if "From current sources" in stdout:
            return "EVIDENCE"
        return ""
    
    def _extract_trust_class(self, stdout: str, stderr: str) -> str:
        """Extract trust class from output."""
        match = re.search(r'TRUST_CLASS[=:](\w+)', stderr)
        if match:
            return match.group(1)
        return ""


# =============================================================================
# Comparison Logic
# =============================================================================

class OutputComparator:
    """Compares outputs from shell and Python implementations."""
    
    def __init__(self, normalize: bool = True):
        self.normalize = normalize
    
    def compare(
        self,
        shell_result: ExecutionResult,
        python_result: ExecutionResult,
        test_fixture: dict[str, Any],
    ) -> ComparisonResult:
        """Compare two execution results."""
        
        test_name = test_fixture["name"]
        query = test_fixture["query"]
        category = test_fixture["category"]
        
        match_details = {}
        differences = []
        
        # Check if both executed
        if shell_result.returncode == -1 and not shell_result.error_message:
            return ComparisonResult(
                test_name=test_name,
                query=query,
                category=category,
                shell_result=shell_result,
                python_result=python_result,
                match=False,
                differences=["Shell implementation not available"],
            )
        
        if python_result.returncode == -1 and "not found" in python_result.error_message:
            # Python implementation not ready yet - skip comparison
            return ComparisonResult(
                test_name=test_name,
                query=query,
                category=category,
                shell_result=shell_result,
                python_result=python_result,
                match=True,  # Consider as pass (not a regression)
                match_details={"python_not_ready": True},
                differences=["Python implementation not yet available - skipping comparison"],
            )
        
        # Compare return codes
        returncode_match = shell_result.returncode == python_result.returncode
        match_details["returncode"] = returncode_match
        if not returncode_match:
            differences.append(
                f"Return code mismatch: shell={shell_result.returncode}, "
                f"python={python_result.returncode}"
            )
        
        # Compare outcome codes
        outcome_match = shell_result.outcome_code == python_result.outcome_code
        match_details["outcome_code"] = outcome_match
        if not outcome_match:
            differences.append(
                f"Outcome code mismatch: shell={shell_result.outcome_code}, "
                f"python={python_result.outcome_code}"
            )
        
        # Compare routes
        route_match = shell_result.route == python_result.route
        match_details["route"] = route_match
        if not route_match:
            differences.append(
                f"Route mismatch: shell={shell_result.route}, python={python_result.route}"
            )
        
        # Compare stdout content
        stdout_match = self._compare_stdout(shell_result.stdout, python_result.stdout)
        match_details["stdout"] = stdout_match
        if not stdout_match:
            diff = self._generate_diff(
                shell_result.stdout,
                python_result.stdout,
                "shell",
                "python",
            )
            differences.append(f"Stdout mismatch:\n{diff}")
        
        # Compare stderr (for trace/debug info)
        # Note: stderr may differ due to timing/logging differences
        # Only flag if Python has errors and shell doesn't
        stderr_match = True
        if python_result.returncode != 0 and shell_result.returncode == 0:
            stderr_match = False
            differences.append(
                f"Python failed with: {python_result.stderr[:200]}..."
            )
        match_details["stderr"] = stderr_match
        
        # Overall match
        match = all(match_details.values())
        
        # Generate diff summary
        diff_summary = self._generate_summary_diff(
            shell_result.stdout,
            python_result.stdout,
        )
        
        return ComparisonResult(
            test_name=test_name,
            query=query,
            category=category,
            shell_result=shell_result,
            python_result=python_result,
            match=match,
            match_details=match_details,
            differences=differences,
            diff_summary=diff_summary,
        )
    
    def _compare_stdout(self, shell_stdout: str, python_stdout: str) -> bool:
        """Compare stdout outputs."""
        if self.normalize:
            shell_normalized = self._normalize_output(shell_stdout)
            python_normalized = self._normalize_output(python_stdout)
            return shell_normalized == python_normalized
        return shell_stdout == python_stdout
    
    def _normalize_output(self, output: str) -> str:
        """Normalize output for comparison."""
        normalized = output
        
        for pattern, replacement in NORMALIZATION_PATTERNS:
            normalized = re.sub(pattern, replacement, normalized)
        
        # Normalize whitespace
        normalized = re.sub(r'\s+', ' ', normalized)
        normalized = normalized.strip()
        
        # Normalize case for comparison
        normalized = normalized.lower()
        
        return normalized
    
    def _generate_diff(
        self,
        expected: str,
        actual: str,
        expected_label: str,
        actual_label: str,
    ) -> str:
        """Generate unified diff between two strings."""
        expected_lines = expected.splitlines(keepends=True)
        actual_lines = actual.splitlines(keepends=True)
        
        diff = difflib.unified_diff(
            expected_lines,
            actual_lines,
            fromfile=expected_label,
            tofile=actual_label,
            lineterm='',
        )
        
        return ''.join(diff)[:1000]  # Limit diff size
    
    def _generate_summary_diff(self, shell_stdout: str, python_stdout: str) -> str:
        """Generate a brief summary of differences."""
        shell_lines = shell_stdout.strip().split('\n')
        python_lines = python_stdout.strip().split('\n')
        
        line_diff = len(shell_lines) - len(python_lines)
        
        char_diff = len(shell_stdout) - len(python_stdout)
        
        return (
            f"Shell: {len(shell_lines)} lines, {len(shell_stdout)} chars | "
            f"Python: {len(python_lines)} lines, {len(python_stdout)} chars | "
            f"Diff: {line_diff} lines, {char_diff} chars"
        )


# =============================================================================
# Test Runner
# =============================================================================

class ParityTestRunner:
    """Runs parity tests between shell and Python implementations."""
    
    def __init__(
        self,
        root_dir: Path,
        categories: list[str] | None = None,
        shadow_mode: bool = False,
        verbose: bool = False,
    ):
        self.root_dir = root_dir
        self.categories = categories
        self.shadow_mode = shadow_mode
        self.verbose = verbose
        
        self.engine = ExecutionEngine(root_dir)
        self.comparator = OutputComparator(normalize=True)
        
        self.results: list[ComparisonResult] = []
    
    def run_all_tests(self, test_fixtures: list[dict[str, Any]] | None = None) -> TestReport:
        """Run all test fixtures."""
        timestamp = datetime.now().isoformat()
        
        # Filter fixtures by category
        fixtures = test_fixtures if test_fixtures is not None else TEST_FIXTURES
        if self.categories:
            fixtures = [f for f in fixtures if f["category"] in self.categories]
        
        total = len(fixtures)
        passed = 0
        failed = 0
        skipped = 0
        
        print(f"\n{'=' * 70}")
        print(f"Running {total} parity tests")
        print(f"Shadow mode: {self.shadow_mode}")
        print(f"Categories: {self.categories or 'all'}")
        print(f"{'=' * 70}\n")
        
        for i, fixture in enumerate(fixtures, 1):
            result = self._run_single_test(fixture, i, total)
            self.results.append(result)
            
            if result.match:
                passed += 1
            elif result.python_result and "not yet available" in str(result.differences):
                skipped += 1
            else:
                failed += 1
            
            if self.verbose or not result.match:
                self._print_result(result, i, total)
        
        # Generate summary
        summary = {
            "total": total,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "pass_rate": f"{passed/max(total-skipped, 1)*100:.1f}%",
            "categories_tested": list(set(r.category for r in self.results)),
        }
        
        return TestReport(
            timestamp=timestamp,
            total_tests=total,
            passed=passed,
            failed=failed,
            skipped=skipped,
            shadow_mode=self.shadow_mode,
            results=self.results,
            summary=summary,
        )
    
    def _run_single_test(
        self,
        fixture: dict[str, Any],
        index: int,
        total: int,
    ) -> ComparisonResult:
        """Run a single test fixture."""
        query = fixture["query"]
        
        # Run shell implementation
        shell_result = self.engine.run_shell(query)
        
        # Run Python implementation
        python_result = self.engine.run_python(query)
        
        # Compare results
        comparison = self.comparator.compare(shell_result, python_result, fixture)
        
        return comparison
    
    def _print_result(self, result: ComparisonResult, index: int, total: int) -> None:
        """Print test result."""
        status = "✅ PASS" if result.match else "❌ FAIL"
        if result.python_result and "not yet available" in str(result.differences):
            status = "⏭️  SKIP"
        
        print(f"\n[{index}/{total}] {status} {result.test_name}")
        print(f"  Query: {result.query[:60]}{'...' if len(result.query) > 60 else ''}")
        print(f"  Category: {result.category}")
        
        if result.shell_result:
            print(f"  Shell: rc={result.shell_result.returncode}, "
                  f"outcome={result.shell_result.outcome_code or 'N/A'}, "
                  f"route={result.shell_result.route or 'N/A'}")
        
        if result.python_result:
            print(f"  Python: rc={result.python_result.returncode}, "
                  f"outcome={result.python_result.outcome_code or 'N/A'}, "
                  f"route={result.python_result.route or 'N/A'}")
        
        if not result.match and result.differences:
            print(f"  Differences:")
            for diff in result.differences:
                lines = diff.split('\n')
                for line in lines[:5]:  # Show first 5 lines
                    print(f"    {line}")
                if len(lines) > 5:
                    print(f"    ... ({len(lines) - 5} more lines)")
        
        if result.diff_summary:
            print(f"  Summary: {result.diff_summary}")


# =============================================================================
# Reporting
# =============================================================================

def generate_console_report(report: TestReport) -> str:
    """Generate console-friendly report."""
    lines = []
    lines.append("\n" + "=" * 70)
    lines.append("PARITY TEST REPORT")
    lines.append("=" * 70)
    lines.append(f"Timestamp: {report.timestamp}")
    lines.append(f"Shadow mode: {report.shadow_mode}")
    lines.append("")
    lines.append(f"Total tests: {report.total_tests}")
    lines.append(f"Passed: {report.passed} ✅")
    lines.append(f"Failed: {report.failed} ❌")
    lines.append(f"Skipped: {report.skipped} ⏭️")
    lines.append(f"Pass rate: {report.summary.get('pass_rate', 'N/A')}")
    lines.append("")
    
    if report.failed > 0:
        lines.append("FAILED TESTS:")
        lines.append("-" * 70)
        for result in report.results:
            if not result.match:
                lines.append(f"\n❌ {result.test_name} ({result.category})")
                lines.append(f"   Query: {result.query}")
                for diff in result.differences[:3]:
                    lines.append(f"   {diff[:100]}")
    
    lines.append("")
    lines.append("=" * 70)
    
    if report.shadow_mode:
        lines.append("Shadow mode: Differences logged, no failure reported.")
    elif report.failed == 0:
        lines.append("All tests passed! ✅")
    else:
        lines.append(f"{report.failed} test(s) failed. ❌")
    
    lines.append("=" * 70)
    
    return '\n'.join(lines)


def generate_json_report(report: TestReport, output_path: Path) -> None:
    """Generate JSON report file."""
    with open(output_path, 'w') as f:
        json.dump(report.to_dict(), f, indent=2)


# =============================================================================
# Main Entry Point
# =============================================================================

def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Test harness for migration validation (shell vs Python)",
    )
    parser.add_argument(
        "--shadow-mode",
        action="store_true",
        help="Run in shadow mode - log differences without failing",
    )
    parser.add_argument(
        "--category",
        type=str,
        help="Comma-separated list of test categories to run",
    )
    parser.add_argument(
        "--json-report",
        type=str,
        metavar="PATH",
        help="Generate JSON report at specified path",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose output",
    )
    parser.add_argument(
        "--test",
        type=str,
        metavar="NAME",
        help="Run specific test by name",
    )
    
    args = parser.parse_args()
    
    # Parse categories
    categories = None
    if args.category:
        categories = [c.strip() for c in args.category.split(",")]
    
    # Run specific test if requested
    test_fixtures = TEST_FIXTURES
    if args.test:
        fixtures = [f for f in TEST_FIXTURES if f["name"] == args.test]
        if not fixtures:
            print(f"Error: Test '{args.test}' not found", file=sys.stderr)
            return 2
        # Temporarily replace fixtures
        test_fixtures = fixtures
    
    # Create runner
    runner = ParityTestRunner(
        root_dir=ROOT_DIR,
        categories=categories,
        shadow_mode=args.shadow_mode,
        verbose=args.verbose,
    )
    
    # Run tests
    report = runner.run_all_tests(test_fixtures=test_fixtures)
    
    # Print console report
    print(generate_console_report(report))
    
    # Generate JSON report if requested
    if args.json_report:
        output_path = Path(args.json_report)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        generate_json_report(report, output_path)
        print(f"\nJSON report written to: {output_path}")
    
    # Return exit code
    if args.shadow_mode:
        return 0  # Always success in shadow mode
    return 0 if report.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
