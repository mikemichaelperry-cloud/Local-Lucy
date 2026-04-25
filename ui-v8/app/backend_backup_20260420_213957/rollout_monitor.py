#!/usr/bin/env python3
"""
Rollout Monitoring Dashboard

Tracks metrics during Python router rollout:
- Query volumes (shell vs Python)
- Error rates
- Performance comparison
- Classification distribution

Usage:
    python3 rollout_monitor.py --live      # Monitor live logs
    python3 rollout_monitor.py --report    # Generate report from saved logs
    python3 rollout_monitor.py --alert     # Check thresholds, exit non-zero if violated
"""

import argparse
import json
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
LOG_DIR = ROOT_DIR / "logs" / "router_py_shadow"


def parse_shadow_logs() -> list[dict]:
    """Parse all shadow log files."""
    logs = []
    
    if not LOG_DIR.exists():
        return logs
    
    for log_file in LOG_DIR.glob("shadow_diff_*.json"):
        try:
            with open(log_file) as f:
                data = json.load(f)
                data['file'] = str(log_file)
                logs.append(data)
        except (json.JSONDecodeError, IOError):
            continue
    
    return logs


def analyze_rollout_metrics(logs: list[dict]) -> dict:
    """Analyze rollout metrics from logs."""
    metrics = {
        'total_queries': len(logs),
        'by_classification': defaultdict(int),
        'by_hour': defaultdict(int),
        'error_rate': 0.0,
        'avg_speedup': 0.0,
        'hard_regressions': 0,
        'suspicious_drifts': 0,
        'recent_errors': [],
    }
    
    speedups = []
    
    for log in logs:
        # Classification
        classification = log.get('classification', 'unknown')
        metrics['by_classification'][classification] += 1
        
        # Hour bucket
        timestamp = log.get('timestamp', '')
        if timestamp:
            try:
                hour = timestamp[:13]  # YYYY-MM-DDTHH
                metrics['by_hour'][hour] += 1
            except:
                pass
        
        # Performance
        shell = log.get('shell', {})
        python = log.get('python', {})
        if shell and python:
            shell_time = shell.get('execution_time_ms', 0)
            python_time = python.get('execution_time_ms', 0)
            if python_time > 0:
                speedup = shell_time / python_time
                speedups.append(speedup)
        
        # Issues
        if classification == 'hard_regression':
            metrics['hard_regressions'] += 1
            metrics['recent_errors'].append({
                'time': timestamp,
                'query': log.get('query', '')[:50],
                'issue': 'hard_regression',
            })
        elif classification == 'suspicious_drift':
            metrics['suspicious_drifts'] += 1
            metrics['recent_errors'].append({
                'time': timestamp,
                'query': log.get('query', '')[:50],
                'issue': 'suspicious_drift',
            })
    
    if speedups:
        metrics['avg_speedup'] = sum(speedups) / len(speedups)
    
    total = len(logs)
    if total > 0:
        metrics['error_rate'] = (metrics['hard_regressions'] + metrics['suspicious_drifts']) / total
    
    return metrics


def print_dashboard(metrics: dict):
    """Print monitoring dashboard."""
    print("\n" + "=" * 60)
    print("PYTHON ROUTER ROLLOUT MONITOR")
    print("=" * 60)
    print(f"Time: {datetime.now().isoformat()}")
    print(f"Log Directory: {LOG_DIR}")
    
    print(f"\n📊 Total Queries Logged: {metrics['total_queries']}")
    
    # Classification breakdown
    print("\n📈 Classification Distribution:")
    total = metrics['total_queries']
    if total > 0:
        for cls, count in sorted(metrics['by_classification'].items()):
            pct = 100 * count / total
            bar = "█" * int(pct / 5)
            print(f"  {cls:<20} {count:>4} ({pct:5.1f}%) {bar}")
    
    # Performance
    print(f"\n⚡ Performance:")
    print(f"  Average Speedup: {metrics['avg_speedup']:.2f}x")
    if metrics['avg_speedup'] < 1.0:
        print(f"  ⚠️  WARNING: Python is slower than shell!")
    
    # Issues
    print(f"\n🚨 Issues:")
    print(f"  Hard Regressions: {metrics['hard_regressions']}")
    print(f"  Suspicious Drifts: {metrics['suspicious_drifts']}")
    print(f"  Error Rate: {100*metrics['error_rate']:.2f}%")
    
    if metrics['recent_errors']:
        print(f"\n  Recent Issues (last 5):")
        for err in metrics['recent_errors'][-5:]:
            print(f"    - [{err['issue']}] {err['query'][:50]}...")
    
    # Health check
    print(f"\n🏥 Health Check:")
    healthy = True
    
    if metrics['hard_regressions'] > 0:
        print(f"  ❌ FAIL: {metrics['hard_regressions']} hard regression(s) detected")
        healthy = False
    else:
        print(f"  ✅ PASS: No hard regressions")
    
    if metrics['error_rate'] > 0.05:
        print(f"  ❌ FAIL: Error rate {100*metrics['error_rate']:.1f}% > 5%")
        healthy = False
    else:
        print(f"  ✅ PASS: Error rate {100*metrics['error_rate']:.1f}% <= 5%")
    
    if metrics['avg_speedup'] < 0.8:
        print(f"  ⚠️  WARN: Speedup {metrics['avg_speedup']:.2f}x < 0.8x")
    else:
        print(f"  ✅ PASS: Speedup {metrics['avg_speedup']:.2f}x acceptable")
    
    print("=" * 60)
    
    return healthy


def check_alert_thresholds(metrics: dict) -> int:
    """Check if any alert thresholds are violated."""
    violations = []
    
    # Threshold: No hard regressions allowed
    if metrics['hard_regressions'] > 0:
        violations.append(f"Hard regressions: {metrics['hard_regressions']}")
    
    # Threshold: Max 5% error rate
    if metrics['error_rate'] > 0.05:
        violations.append(f"Error rate: {100*metrics['error_rate']:.1f}% > 5%")
    
    # Threshold: Python shouldn't be more than 2x slower
    if metrics['avg_speedup'] < 0.5:
        violations.append(f"Speedup: {metrics['avg_speedup']:.2f}x < 0.5x")
    
    if violations:
        print("ALERT: Threshold violations detected:")
        for v in violations:
            print(f"  - {v}")
        return 1
    else:
        print("OK: All thresholds within acceptable range")
        return 0


def live_monitor(interval: int = 30):
    """Live monitoring mode."""
    print("Live Monitoring Mode")
    print(f"Checking every {interval} seconds. Press Ctrl+C to exit.")
    print("=" * 60)
    
    try:
        while True:
            logs = parse_shadow_logs()
            metrics = analyze_rollout_metrics(logs)
            
            # Clear screen (Unix-like)
            print("\033[2J\033[H")
            
            healthy = print_dashboard(metrics)
            
            if not healthy:
                print("\n⚠️  Health check FAILED - review recommended")
            
            print(f"\n⏱️  Next update in {interval}s...")
            time.sleep(interval)
            
    except KeyboardInterrupt:
        print("\n\nMonitoring stopped.")


def generate_report():
    """Generate comprehensive report."""
    logs = parse_shadow_logs()
    metrics = analyze_rollout_metrics(logs)
    
    print_dashboard(metrics)
    
    # Save report
    report_file = LOG_DIR / f"rollout_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    report_data = {
        'timestamp': datetime.now().isoformat(),
        'metrics': metrics,
    }
    
    with open(report_file, 'w') as f:
        json.dump(report_data, f, indent=2, default=str)
    
    print(f"\nReport saved: {report_file}")


def main():
    parser = argparse.ArgumentParser(description="Rollout Monitoring Dashboard")
    parser.add_argument("--live", action="store_true", help="Live monitoring mode")
    parser.add_argument("--interval", type=int, default=30, help="Update interval (seconds)")
    parser.add_argument("--report", action="store_true", help="Generate report")
    parser.add_argument("--alert", action="store_true", help="Check thresholds, exit non-zero if violated")
    args = parser.parse_args()
    
    if args.live:
        live_monitor(args.interval)
    elif args.alert:
        logs = parse_shadow_logs()
        metrics = analyze_rollout_metrics(logs)
        return check_alert_thresholds(metrics)
    else:
        generate_report()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
