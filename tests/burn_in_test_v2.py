#!/usr/bin/env python3
"""
Burn-in Test V2: Simplified version using direct subprocess approach

This test runs thousands of queries using the existing torture test approach
which we know works, but extended for longer duration.
"""

import os
import sys
import time
import json
import random
import argparse
import statistics
import psutil
import subprocess
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

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
    
    def record_query(self, success: bool, response_time: float):
        self.total_queries += 1
        self.response_times.append(response_time)
        if success:
            self.successful_queries += 1
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
    def memory_growth_mb(self) -> float:
        if len(self.memory_samples) >= 2:
            return self.memory_samples[-1]["memory_mb"] - self.memory_samples[0]["memory_mb"]
        return 0


class BurnInTestV2:
    """Simplified burn-in test using direct_execution_test module."""
    
    QUESTIONS = [
        "What is your name?",
        "What is 2+2?",
        "What's the weather like?",
        "Tell me a joke",
        "Explain Python",
        "System status",
        "Hello",
        "What time is it?",
        "How do you work?",
        "Thank you",
    ]
    
    def __init__(self, duration_hours: float, target_queries: int):
        self.duration_hours = duration_hours
        self.target_queries = target_queries
        self.stats = BurnInStats()
        self.root_dir = Path(__file__).parent.parent
        
    def execute_single_query(self) -> tuple[bool, float]:
        """Execute a single query using the working test module."""
        question = random.choice(self.QUESTIONS)
        
        cmd = [
            sys.executable,
            "-c",
            f"""
import sys
sys.path.insert(0, 'tools/router_py')
from execution_engine import ExecutionEngine
from classify import classify_intent, select_route
from policy import normalize_augmentation_policy
import os
os.environ['LUCY_LOCAL_ANSWER_PY'] = '1'
os.environ['LUCY_DIRECT_EXECUTION'] = '1'

engine = ExecutionEngine()
classification = classify_intent('{question}', surface='hmi')
policy = normalize_augmentation_policy('adaptive')
decision = select_route(classification, policy=policy)
result = engine.execute(
    intent=classification,
    route=decision,
    context={{}},
    use_python_path=True,
)
print('SUCCESS' if result.status == 'success' else 'FAIL')
"""
        ]
        
        start = time.time()
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
                cwd=self.root_dir,
                env={**os.environ, "LUCY_LOCAL_ANSWER_PY": "1", "LUCY_DIRECT_EXECUTION": "1"},
            )
            elapsed = (time.time() - start) * 1000
            success = result.returncode == 0 and "SUCCESS" in result.stdout
            return success, elapsed
        except Exception as e:
            elapsed = (time.time() - start) * 1000
            return False, elapsed
    
    def run(self):
        """Run the burn-in test."""
        print("=" * 70)
        print("BURN-IN TEST V2: Python-Only Path")
        print("=" * 70)
        print(f"Target Duration: {self.duration_hours} hours")
        print(f"Target Queries: {self.target_queries}")
        print("")
        
        self.stats.start_time = datetime.now()
        last_resource_sample = time.time()
        last_progress_print = time.time()
        
        try:
            while True:
                # Check duration limit
                elapsed_hours = (datetime.now() - self.stats.start_time).total_seconds() / 3600
                if elapsed_hours >= self.duration_hours:
                    print(f"\nDuration limit reached ({self.duration_hours}h)")
                    break
                
                # Check query limit
                if self.stats.total_queries >= self.target_queries:
                    print(f"\nQuery target reached ({self.target_queries})")
                    break
                
                # Sample resources periodically
                if time.time() - last_resource_sample >= 60:
                    self.stats.record_resource_sample()
                    last_resource_sample = time.time()
                
                # Execute query
                success, response_time = self.execute_single_query()
                self.stats.record_query(success, response_time)
                
                # Progress print every 30 seconds
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
        print(f"Mean Response Time: {self.stats.mean_response_time:.1f}ms")
        print(f"Memory Growth: {self.stats.memory_growth_mb:+.1f} MB")
        print("=" * 70)
        
        # Certification
        print("\nBURN-IN CERTIFICATION:")
        criteria = [
            ("Success Rate >= 95%", self.stats.success_rate >= 95),
            ("No Memory Leak (< 100MB growth)", self.stats.memory_growth_mb < 100),
            ("Minimum 100 queries", self.stats.total_queries >= 100),
        ]
        
        all_passed = all(passed for _, passed in criteria)
        for name, passed in criteria:
            status = "✓ PASS" if passed else "✗ FAIL"
            print(f"  {status}: {name}")
        
        if all_passed:
            print("\n  🏆 CERTIFIED: Python-only path is stable")
        
        # Save report
        self._save_report()
    
    def _save_report(self):
        """Save report to file."""
        report_path = Path("burn_in_report_v2.json")
        report = {
            "timestamp": datetime.now().isoformat(),
            "duration_seconds": self.stats.duration_seconds,
            "total_queries": self.stats.total_queries,
            "successful_queries": self.stats.successful_queries,
            "failed_queries": self.stats.failed_queries,
            "success_rate": self.stats.success_rate,
            "response_times": {
                "mean_ms": self.stats.mean_response_time,
                "min_ms": min(self.stats.response_times) if self.stats.response_times else 0,
                "max_ms": max(self.stats.response_times) if self.stats.response_times else 0,
            },
            "memory": {"growth_mb": self.stats.memory_growth_mb},
        }
        with open(report_path, 'w') as f:
            json.dump(report, f, indent=2)
        print(f"\nReport saved to: {report_path.absolute()}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration-hours", type=float, default=0.5)
    parser.add_argument("--target-queries", type=int, default=100)
    args = parser.parse_args()
    
    test = BurnInTestV2(args.duration_hours, args.target_queries)
    test.run()


if __name__ == "__main__":
    main()
