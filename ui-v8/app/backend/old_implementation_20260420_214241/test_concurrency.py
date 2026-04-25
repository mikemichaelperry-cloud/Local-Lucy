#!/usr/bin/env python3
"""
Concurrency and Race Condition Tests for Lucy V8 Router.

Tests StateManager, ExecutionEngine, and locking mechanisms under concurrent load.
"""

import concurrent.futures
import os
import random
import sqlite3
import statistics
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

# Add parent to path for imports
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR / "tools"))

from backend.state_manager import get_state_manager, StateManager


class ConcurrencyTestResults:
    """Collects and formats test results."""
    
    def __init__(self):
        self.tests = []
        self.start_time = time.time()
    
    def add_test(self, name: str, passed: bool, details: dict = None, error: str = None):
        self.tests.append({
            "name": name,
            "passed": passed,
            "details": details or {},
            "error": error,
            "duration_ms": 0
        })
    
    def summary(self) -> dict:
        passed = sum(1 for t in self.tests if t["passed"])
        failed = len(self.tests) - passed
        return {
            "total": len(self.tests),
            "passed": passed,
            "failed": failed,
            "duration_sec": time.time() - self.start_time
        }
    
    def print_report(self):
        print("\n" + "=" * 70)
        print("CONCURRENCY TEST RESULTS")
        print("=" * 70)
        
        for test in self.tests:
            status = "✅ PASS" if test["passed"] else "❌ FAIL"
            print(f"\n{status}: {test['name']}")
            if test["details"]:
                for key, value in test["details"].items():
                    print(f"  {key}: {value}")
            if test["error"]:
                print(f"  Error: {test['error']}")
        
        summary = self.summary()
        print("\n" + "=" * 70)
        print(f"SUMMARY: {summary['passed']}/{summary['total']} passed")
        print(f"Total duration: {summary['duration_sec']:.2f}s")
        print("=" * 70)


results = ConcurrencyTestResults()


# =============================================================================
# TEST 1: StateManager Concurrent Writes
# =============================================================================
def test_statemanager_concurrent_writes():
    """Test multiple threads writing routes concurrently."""
    print("\n--- Test 1: StateManager Concurrent Writes ---")
    
    namespace = f"concurrency_test_{int(time.time() * 1000)}"
    sm = get_state_manager(namespace)
    
    num_threads = 10
    writes_per_thread = 20
    errors = []
    write_times = []
    
    def worker(worker_id):
        thread_errors = []
        thread_times = []
        for i in range(writes_per_thread):
            start = time.time()
            try:
                success = sm.write_route({
                    "intent": f"worker_{worker_id}",
                    "confidence": 0.9,
                    "strategy": "LOCAL",
                    "metadata": {"iteration": i, "worker": worker_id}
                })
                if not success:
                    thread_errors.append(f"Worker {worker_id}, iter {i}: write failed")
            except Exception as e:
                thread_errors.append(f"Worker {worker_id}, iter {i}: {e}")
            thread_times.append(time.time() - start)
            time.sleep(0.001)  # Small delay to increase contention
        return thread_errors, thread_times
    
    start_time = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(worker, i) for i in range(num_threads)]
        for future in concurrent.futures.as_completed(futures):
            err, times = future.result()
            errors.extend(err)
            write_times.extend(times)
    
    total_time = time.time() - start_time
    
    # Verify all writes succeeded
    routes = sm.read_routes(limit=1000)
    expected = num_threads * writes_per_thread
    actual = len(routes)
    
    # Check for unique iterations per worker
    worker_iterations = {}
    for route in routes:
        worker = route["metadata"].get("worker", -1)
        iteration = route["metadata"].get("iteration", -1)
        if worker not in worker_iterations:
            worker_iterations[worker] = set()
        worker_iterations[worker].add(iteration)
    
    passed = (actual == expected and len(errors) == 0)
    
    details = {
        "threads": num_threads,
        "writes_per_thread": writes_per_thread,
        "expected_writes": expected,
        "actual_writes": actual,
        "errors": len(errors),
        "total_time_sec": round(total_time, 3),
        "avg_write_time_ms": round(statistics.mean(write_times) * 1000, 3) if write_times else 0,
        "workers_with_all_iterations": sum(1 for w, iters in worker_iterations.items() 
                                           if len(iters) == writes_per_thread)
    }
    
    error_msg = None
    if errors:
        error_msg = errors[0] if len(errors) <= 3 else f"{errors[0]} (and {len(errors)-1} more)"
    elif actual != expected:
        error_msg = f"Write count mismatch: expected {expected}, got {actual}"
    
    results.add_test("StateManager Concurrent Writes", passed, details, error_msg)
    
    sm.close()
    return passed


# =============================================================================
# TEST 2: StateManager Lock Contention
# =============================================================================
def test_statemanager_lock_contention():
    """Test lock acquisition under high contention."""
    print("\n--- Test 2: StateManager Lock Contention ---")
    
    namespace = f"lock_test_{int(time.time() * 1000)}"
    lock_name = "test_contention_lock"
    
    num_workers = 20
    successful_locks = 0
    failed_locks = 0
    lock_times = []
    errors = []
    
    def lock_worker(worker_id):
        nonlocal successful_locks, failed_locks
        sm = get_state_manager(namespace)
        
        start = time.time()
        try:
            if sm.acquire_lock(f"{lock_name}_{worker_id % 5}", timeout=2.0):
                lock_time = time.time() - start
                lock_times.append(lock_time)
                successful_locks += 1
                time.sleep(0.05)  # Hold lock briefly
                sm.release_lock(f"{lock_name}_{worker_id % 5}")
            else:
                failed_locks += 1
        except Exception as e:
            errors.append(f"Worker {worker_id}: {e}")
        finally:
            sm.close()
    
    start_time = time.time()
    threads = [threading.Thread(target=lock_worker, args=(i,)) for i in range(num_workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    
    total_time = time.time() - start_time
    
    # Verify no deadlocks (all threads completed)
    alive_threads = sum(1 for t in threads if t.is_alive())
    
    passed = (alive_threads == 0 and len(errors) == 0 and successful_locks > 0)
    
    details = {
        "workers": num_workers,
        "successful_locks": successful_locks,
        "failed_locks": failed_locks,
        "alive_threads": alive_threads,
        "errors": len(errors),
        "avg_lock_time_ms": round(statistics.mean(lock_times) * 1000, 3) if lock_times else 0,
        "total_time_sec": round(total_time, 3)
    }
    
    error_msg = None
    if alive_threads > 0:
        error_msg = f"{alive_threads} threads still alive (possible deadlock)"
    elif errors:
        error_msg = errors[0]
    
    results.add_test("StateManager Lock Contention", passed, details, error_msg)
    return passed


# =============================================================================
# TEST 3: Database Connection Pool Stress Test
# =============================================================================
def test_connection_pool_stress():
    """Test connection reuse under high thread count."""
    print("\n--- Test 3: Connection Pool Stress Test ---")
    
    namespace = f"pool_test_{int(time.time() * 1000)}"
    num_threads = 50
    operations_per_thread = 10
    errors = []
    
    def pool_worker(worker_id):
        thread_errors = []
        try:
            sm = get_state_manager(namespace)
            for i in range(operations_per_thread):
                # Mix of reads and writes
                if i % 2 == 0:
                    sm.write_route({
                        "intent": f"pool_worker_{worker_id}",
                        "confidence": 0.85,
                        "strategy": "TEST"
                    })
                else:
                    sm.read_last_route()
                time.sleep(0.001)
            sm.close()
        except Exception as e:
            thread_errors.append(f"Worker {worker_id}: {e}")
        return thread_errors
    
    start_time = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(pool_worker, i) for i in range(num_threads)]
        for future in concurrent.futures.as_completed(futures):
            err = future.result()
            errors.extend(err)
    
    total_time = time.time() - start_time
    
    passed = len(errors) == 0
    
    details = {
        "threads": num_threads,
        "operations_per_thread": operations_per_thread,
        "total_operations": num_threads * operations_per_thread,
        "errors": len(errors),
        "total_time_sec": round(total_time, 3),
        "ops_per_sec": round((num_threads * operations_per_thread) / total_time, 2)
    }
    
    error_msg = errors[0] if errors else None
    
    results.add_test("Connection Pool Stress Test", passed, details, error_msg)
    return passed


# =============================================================================
# TEST 4: Concurrent Session Operations
# =============================================================================
def test_concurrent_sessions():
    """Test concurrent session read/write operations."""
    print("\n--- Test 4: Concurrent Session Operations ---")
    
    namespace = f"session_test_{int(time.time() * 1000)}"
    sm = get_state_manager(namespace)
    
    num_threads = 10
    errors = []
    
    def session_worker(worker_id):
        thread_errors = []
        try:
            session_key = f"session_{worker_id % 3}"  # 3 sessions, 10 workers
            for i in range(5):
                # Write session
                sm.write_session(session_key, {
                    "worker": worker_id,
                    "iteration": i,
                    "data": f"value_{i}"
                }, ttl_seconds=60)
                
                # Read session (may get different worker's data)
                data = sm.read_session(session_key)
                
                # Small delay
                time.sleep(0.01)
        except Exception as e:
            thread_errors.append(f"Worker {worker_id}: {e}")
        return thread_errors
    
    start_time = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(session_worker, i) for i in range(num_threads)]
        for future in concurrent.futures.as_completed(futures):
            err = future.result()
            errors.extend(err)
    
    total_time = time.time() - start_time
    
    # Verify sessions exist
    sessions_found = 0
    for i in range(3):
        if sm.read_session(f"session_{i}") is not None:
            sessions_found += 1
    
    passed = len(errors) == 0 and sessions_found > 0
    
    details = {
        "threads": num_threads,
        "unique_sessions": 3,
        "sessions_found": sessions_found,
        "errors": len(errors),
        "total_time_sec": round(total_time, 3)
    }
    
    error_msg = errors[0] if errors else None
    if not error_msg and sessions_found == 0:
        error_msg = "No sessions found after concurrent writes"
    
    results.add_test("Concurrent Session Operations", passed, details, error_msg)
    
    sm.close()
    return passed


# =============================================================================
# TEST 5: Race Condition - Read-Modify-Write
# =============================================================================
def test_race_condition_read_modify_write():
    """Test for race conditions in read-modify-write patterns."""
    print("\n--- Test 5: Race Condition - Read-Modify-Write ---")
    
    namespace = f"race_test_{int(time.time() * 1000)}"
    sm = get_state_manager(namespace)
    
    # Initialize a counter
    sm.write_session("counter", {"value": 0}, ttl_seconds=300)
    
    num_threads = 20
    increments_per_thread = 50
    errors = []
    
    def increment_worker(worker_id):
        thread_errors = []
        try:
            for _ in range(increments_per_thread):
                # Read
                data = sm.read_session("counter")
                current = data.get("value", 0) if data else 0
                
                # Modify (no lock - intentional race condition test)
                time.sleep(0.001)  # Small window for race
                
                # Write
                sm.write_session("counter", {"value": current + 1}, ttl_seconds=300)
        except Exception as e:
            thread_errors.append(f"Worker {worker_id}: {e}")
        return thread_errors
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(increment_worker, i) for i in range(num_threads)]
        for future in concurrent.futures.as_completed(futures):
            err = future.result()
            errors.extend(err)
    
    # Check final value (will likely be less than expected due to races)
    final_data = sm.read_session("counter")
    final_value = final_data.get("value", 0) if final_data else 0
    expected_value = num_threads * increments_per_thread
    
    # Note: This test EXPECTS race conditions - it's documenting the behavior
    # In production, use proper locking
    race_lost = expected_value - final_value
    
    passed = len(errors) == 0  # Errors are failures, races are expected
    
    details = {
        "threads": num_threads,
        "increments_per_thread": increments_per_thread,
        "expected_value": expected_value,
        "actual_value": final_value,
        "race_conditions_lost": race_lost,
        "race_percentage": round((race_lost / expected_value) * 100, 1) if expected_value > 0 else 0,
        "errors": len(errors)
    }
    
    error_msg = errors[0] if errors else None
    
    results.add_test("Race Condition - Read-Modify-Write", passed, details, error_msg)
    
    sm.close()
    return passed


# =============================================================================
# TEST 6: WAL Mode Verification
# =============================================================================
def test_wal_mode():
    """Verify SQLite is running in WAL mode for concurrent access."""
    print("\n--- Test 6: WAL Mode Verification ---")
    
    namespace = f"wal_test_{int(time.time() * 1000)}"
    sm = get_state_manager(namespace)
    
    try:
        conn = sm._get_connection()
        cursor = conn.execute("PRAGMA journal_mode")
        mode = cursor.fetchone()[0]
        
        cursor = conn.execute("PRAGMA wal_checkpoint")
        checkpoint = cursor.fetchone()
        
        passed = mode.upper() == "WAL"
        
        details = {
            "journal_mode": mode,
            "wal_checkpoint": str(checkpoint) if checkpoint else "N/A"
        }
        
        error_msg = None if passed else f"Expected WAL mode, got {mode}"
        
    except Exception as e:
        passed = False
        details = {}
        error_msg = str(e)
    
    results.add_test("WAL Mode Verification", passed, details, error_msg)
    
    sm.close()
    return passed


# =============================================================================
# TEST 7: Database Timeout and Retry
# =============================================================================
def test_database_timeout():
    """Test database timeout handling under contention."""
    print("\n--- Test 7: Database Timeout Handling ---")
    
    namespace = f"timeout_test_{int(time.time() * 1000)}"
    db_path = sm.db_path if 'sm' in dir() else None
    
    # Create a connection and hold a lock
    sm = get_state_manager(namespace)
    
    # Start a transaction but don't commit (holds lock)
    conn1 = sm._get_connection()
    conn1.execute("BEGIN IMMEDIATE")
    conn1.execute("INSERT INTO routes (namespace_id, intent, confidence, strategy) VALUES (?, ?, ?, ?)",
                  (sm._namespace_id, "lock_holder", 0.5, "TEST"))
    
    errors = []
    timeout_occurred = False
    
    def timeout_worker():
        try:
            sm2 = get_state_manager(namespace)
            # Try to write while lock is held
            sm2.write_route({
                "intent": "contender",
                "confidence": 0.8,
                "strategy": "TEST"
            })
            sm2.close()
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e) or "timeout" in str(e).lower():
                nonlocal timeout_occurred
                timeout_occurred = True
            else:
                errors.append(str(e))
        except Exception as e:
            errors.append(str(e))
    
    # Start worker that will contend for lock
    thread = threading.Thread(target=timeout_worker)
    thread.start()
    thread.join(timeout=5)
    
    # Release lock
    conn1.rollback()
    
    passed = len(errors) == 0
    
    details = {
        "timeout_occurred": timeout_occurred,
        "errors": len(errors)
    }
    
    error_msg = errors[0] if errors else None
    
    results.add_test("Database Timeout Handling", passed, details, error_msg)
    
    sm.close()
    return passed


# =============================================================================
# TEST 8: Telemetry Concurrent Recording
# =============================================================================
def test_concurrent_telemetry():
    """Test concurrent telemetry recording."""
    print("\n--- Test 8: Concurrent Telemetry Recording ---")
    
    namespace = f"telemetry_test_{int(time.time() * 1000)}"
    sm = get_state_manager(namespace)
    
    num_threads = 15
    events_per_thread = 20
    errors = []
    
    def telemetry_worker(worker_id):
        thread_errors = []
        try:
            for i in range(events_per_thread):
                sm.record_telemetry(f"event_type_{worker_id % 3}", {
                    "worker": worker_id,
                    "iteration": i,
                    "timestamp": time.time()
                })
        except Exception as e:
            thread_errors.append(f"Worker {worker_id}: {e}")
        return thread_errors
    
    start_time = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(telemetry_worker, i) for i in range(num_threads)]
        for future in concurrent.futures.as_completed(futures):
            err = future.result()
            errors.extend(err)
    
    total_time = time.time() - start_time
    
    # Verify events were recorded
    summary = sm.get_telemetry_summary()
    total_events = summary.get("total_count", 0)
    expected_events = num_threads * events_per_thread
    
    passed = len(errors) == 0 and total_events == expected_events
    
    details = {
        "threads": num_threads,
        "events_per_thread": events_per_thread,
        "expected_events": expected_events,
        "actual_events": total_events,
        "event_breakdown": summary.get("event_breakdown", {}),
        "errors": len(errors),
        "total_time_sec": round(total_time, 3)
    }
    
    error_msg = None
    if errors:
        error_msg = errors[0]
    elif total_events != expected_events:
        error_msg = f"Event count mismatch: expected {expected_events}, got {total_events}"
    
    results.add_test("Concurrent Telemetry Recording", passed, details, error_msg)
    
    sm.close()
    return passed


# =============================================================================
# MAIN
# =============================================================================
def run_all_tests():
    """Run all concurrency tests."""
    print("=" * 70)
    print("LUCY V8 ROUTER - CONCURRENCY AND RACE CONDITION TESTS")
    print("=" * 70)
    print(f"Started at: {datetime.now().isoformat()}")
    
    tests = [
        test_wal_mode,
        test_statemanager_concurrent_writes,
        test_statemanager_lock_contention,
        test_connection_pool_stress,
        test_concurrent_sessions,
        test_race_condition_read_modify_write,
        test_database_timeout,
        test_concurrent_telemetry,
    ]
    
    for test in tests:
        try:
            test()
        except Exception as e:
            print(f"\n❌ FAIL: {test.__name__} - Uncaught exception: {e}")
            traceback.print_exc()
            results.add_test(test.__name__, False, {}, str(e))
    
    results.print_report()
    
    # Return summary for programmatic use
    return results.summary()


if __name__ == "__main__":
    summary = run_all_tests()
    sys.exit(0 if summary["failed"] == 0 else 1)
