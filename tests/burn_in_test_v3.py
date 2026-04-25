#!/usr/bin/env python3
"""
Burn-in Test V3: Working version with correct imports and attributes

Usage:
    cd /home/mike/lucy-v8/snapshots/opt-experimental-v8-dev
    PYTHONPATH=tools python tests/burn_in_test_v3.py --duration-hours 1 --target-queries 1000
"""

import os
import sys
import time
import json
import random
import argparse
import statistics
import psutil
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

# Ensure router_py can be imported
sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

from router_py.execution_engine import ExecutionEngine
from router_py.classify import classify_intent, select_route
from router_py.policy import normalize_augmentation_policy

# Force Python-only path
os.environ["LUCY_LOCAL_ANSWER_PY"] = "1"
os.environ["LUCY_DIRECT_EXECUTION"] = "1"
os.environ["LUCY_USE_SQLITE_STATE"] = "1"


@dataclass
class BurnInStats:
    """Statistics for burn-in test."""
    total_queries: int = 0
    successful_queries: int = 0
    failed_queries: int = 0
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    response_times: list = field(default_factory=list)
    memory_samples: list = field(default_factory=list)
    pattern_counts: dict = field(default_factory=dict)
    
    def record_query(self, pattern: str, success: bool, response_time: float):
        self.total_queries += 1
        self.response_times.append(response_time)
        if pattern not in self.pattern_counts:
            self.pattern_counts[pattern] = {"total": 0, "success": 0}
        self.pattern_counts[pattern]["total"] += 1
        if success:
            self.successful_queries += 1
            self.pattern_counts[pattern]["success"] += 1
        else:
            self.failed_queries += 1
    
    def record_resource_sample(self):
        process = psutil.Process()
        memory_mb = process.memory_info().rss / 1024 / 1024
        self.memory_samples.append({"timestamp": time.time(), "memory_mb": memory_mb})
    
    @property
    def duration_seconds(self) -> float:
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return 0
    
    @property
    def success_rate(self) -> float:
        if self.total_queries > 0:
            return (self.successful_queries / self.total_queries) * 100
        return 0
    
    @property
    def mean_response_time(self) -> float:
        if self.response_times:
            return statistics.mean(self.response_times)
        return 0
    
    @property
    def p95_response_time(self) -> float:
        if len(self.response_times) >= 20:
            sorted_times = sorted(self.response_times)
            idx = int(len(sorted_times) * 0.95)
            return sorted_times[idx]
        return 0
    
    @property
    def memory_growth_mb(self) -> float:
        if len(self.memory_samples) >= 2:
            return self.memory_samples[-1]["memory_mb"] - self.memory_samples[0]["memory_mb"]
        return 0


class BurnInTestV3:
    """Working burn-in test for Python-only path."""
    
    QUESTION_PATTERNS = [
        ("identity", ["What is your name?", "Who are you?", "What can you do?"]),
        ("arithmetic", ["What is 2+2?", "Calculate 15 * 7", "Square root of 144"]),
        ("weather", ["What's the weather like?", "Is it going to rain today?"]),
        ("status", ["What is your status?", "Are you operational?"]),
        ("creative", ["Tell me a joke", "Give me an inspiring quote"]),
        ("technical", ["Explain Python", "What is machine learning?"]),
        ("random", ["Hello", "Thank you", "Help"]),
    ]
    
    def __init__(self, duration_hours: float, target_queries: int):
        self.duration_hours = duration_hours
        self.target_queries = target_queries
        self.stats = BurnInStats()
        self.engine = ExecutionEngine()
        
    def get_random_question(self) -> tuple[str, str]:
        """Get a random question and its pattern type."""
        pattern, questions = random.choice(self.QUESTION_PATTERNS)
        return pattern, random.choice(questions)
    
    def execute_single_query(self) -> tuple[bool, float, str]:
        """Execute a single query."""
        pattern, question = self.get_random_question()
        
        start = time.time()
        try:
            # Step 1: Classify intent
            classification = classify_intent(question, surface="hmi")
            
            # Step 2: Select route
            policy = normalize_augmentation_policy("adaptive")
            decision = select_route(classification, policy=policy)
            
            # Step 3: Execute
            result = self.engine.execute(
                intent=classification,
                route=decision,
                context={},
                use_python_path=True,
            )
            elapsed = (time.time() - start) * 1000
            
            success = result.status == "completed" and result.outcome_code == "answered"
            return success, elapsed, pattern
            
        except Exception as e:
            elapsed = (time.time() - start) * 1000
            print(f"  Error: {e}")
            return False, elapsed, pattern
    
    def run(self):
        """Run the burn-in test."""
        print("=" * 70)
        print("BURN-IN TEST V3: Python-Only Path")
        print("=" * 70)
        print(f"Target Duration: {self.duration_hours} hours")
        print(f"Target Queries: {self.target_queries}")
        print("")
        
        self.stats.start_time = datetime.now()
        last_resource_sample = time.time()
        last_progress_print = time.time()
        
        try:
            while True:
                # Check limits
                elapsed_hours = (datetime.now() - self.stats.start_time).total_seconds() / 3600
                if elapsed_hours >= self.duration_hours:
                    print(f"\nDuration limit reached ({self.duration_hours}h)")
                    break
                
                if self.stats.total_queries >= self.target_queries:
                    print(f"\nQuery target reached ({self.target_queries})")
                    break
                
                # Sample resources
                if time.time() - last_resource_sample >= 60:
                    self.stats.record_resource_sample()
                    last_resource_sample = time.time()
                
                # Execute query
                success, response_time, pattern = self.execute_single_query()
                self.stats.record_query(pattern, success, response_time)
                
                # Progress print
                if time.time() - last_progress_print >= 30:
                    self._print_progress()
                    last_progress_print = time.time()
                    
        except KeyboardInterrupt:
            print("\n\nInterrupted by user")
        finally:
            self.stats.end_time = datetime.now()
            self._print_final_report()
    
    def _print_progress(self):
        """Print progress update."""
        elapsed_min = self.stats.duration_seconds / 60
        qpm = self.stats.total_queries / elapsed_min if elapsed_min > 0 else 0
        print(f"[{elapsed_min:6.1f}m] Queries: {self.stats.total_queries:5d} | "
              f"Success: {self.stats.success_rate:5.1f}% | "
              f"QPM: {qpm:4.1f} | "
              f"Avg RT: {self.stats.mean_response_time:6.1f}ms")
    
    def _print_final_report(self):
        """Print final report."""
        print("\n" + "=" * 70)
        print("BURN-IN TEST SUMMARY")
        print("=" * 70)
        print(f"Duration: {self.stats.duration_seconds/60:.1f} minutes")
        print(f"Total Queries: {self.stats.total_queries}")
        print(f"Successful: {self.stats.successful_queries}")
        print(f"Failed: {self.stats.failed_queries}")
        print(f"Success Rate: {self.stats.success_rate:.2f}%")
        print(f"\nResponse Times:")
        print(f"  Mean: {self.stats.mean_response_time:.1f}ms")
        print(f"  P95:  {self.stats.p95_response_time:.1f}ms")
        print(f"\nResource Usage:")
        print(f"  Memory Growth: {self.stats.memory_growth_mb:+.1f} MB")
        if self.stats.memory_samples:
            print(f"  Final Memory: {self.stats.memory_samples[-1]['memory_mb']:.1f} MB")
        print(f"\nPattern Breakdown:")
        for pattern, counts in self.stats.pattern_counts.items():
            rate = (counts["success"] / counts["total"] * 100) if counts["total"] > 0 else 0
            print(f"  {pattern:12s}: {counts['success']:4d}/{counts['total']:4d} ({rate:5.1f}%)")
        print("=" * 70)
        
        # Certification
        print("\nBURN-IN CERTIFICATION:")
        criteria = [
            ("Success Rate >= 95%", self.stats.success_rate >= 95),
            ("No Memory Leak (< 100MB growth)", abs(self.stats.memory_growth_mb) < 100),
            ("Minimum 100 queries", self.stats.total_queries >= 100),
            ("Minimum 10 min runtime", self.stats.duration_seconds >= 600),
        ]
        
        all_passed = all(passed for _, passed in criteria)
        for name, passed in criteria:
            status = "✓ PASS" if passed else "✗ FAIL"
            print(f"  {status}: {name}")
        
        if all_passed:
            print("\n  🏆 CERTIFIED: Python-only path is production-ready")
            print("\n  RECOMMENDATION:")
            print("    - Change default LUCY_LOCAL_ANSWER_PY to '1'")
            print("    - Shell fallback can be removed in next release")
        else:
            print("\n  ⚠️  Some criteria not met - review before production")
        
        print("=" * 70)
        self._save_report()
    
    def _save_report(self):
        """Save report to file."""
        report_path = Path("burn_in_report_v3.json")
        report = {
            "timestamp": datetime.now().isoformat(),
            "duration_seconds": self.stats.duration_seconds,
            "total_queries": self.stats.total_queries,
            "successful_queries": self.stats.successful_queries,
            "failed_queries": self.stats.failed_queries,
            "success_rate": self.stats.success_rate,
            "response_times": {
                "mean_ms": self.stats.mean_response_time,
                "p95_ms": self.stats.p95_response_time,
            },
            "memory": {"growth_mb": self.stats.memory_growth_mb},
            "patterns": self.stats.pattern_counts,
        }
        with open(report_path, 'w') as f:
            json.dump(report, f, indent=2)
        print(f"\nReport saved to: {report_path.absolute()}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration-hours", type=float, default=0.5)
    parser.add_argument("--target-queries", type=int, default=100)
    args = parser.parse_args()
    
    test = BurnInTestV3(args.duration_hours, args.target_queries)
    test.run()


if __name__ == "__main__":
    main()
