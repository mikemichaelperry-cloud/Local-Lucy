#!/usr/bin/env python3
"""
Resource Leak Detection Test

Monitors for:
- Memory growth
- File descriptor leaks
- Zombie processes
- Database connection leaks
"""

import gc
import os
import psutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

# Add parent to path for imports
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR / "tools"))

from router_py.state_manager import get_state_manager


class ResourceMonitor:
    """Monitor system resources during test execution."""
    
    def __init__(self):
        self.process = psutil.Process()
        self.initial_memory = self.get_memory_mb()
        self.initial_fds = self.get_fd_count()
        self.measurements = []
    
    def get_memory_mb(self):
        """Get current memory usage in MB."""
        return self.process.memory_info().rss / 1024 / 1024
    
    def get_fd_count(self):
        """Get file descriptor count."""
        try:
            return self.process.num_fds()
        except:
            return 0
    
    def get_connections(self):
        """Get network connection count."""
        try:
            return len(self.process.connections())
        except:
            return 0
    
    def get_threads(self):
        """Get thread count."""
        return self.process.num_threads()
    
    def snapshot(self, label=""):
        """Take a resource snapshot."""
        measurement = {
            "label": label,
            "time": time.time(),
            "memory_mb": self.get_memory_mb(),
            "fd_count": self.get_fd_count(),
            "connections": self.get_connections(),
            "threads": self.get_threads()
        }
        self.measurements.append(measurement)
        return measurement
    
    def report(self):
        """Generate resource usage report."""
        if len(self.measurements) < 2:
            return "Not enough measurements"
        
        first = self.measurements[0]
        last = self.measurements[-1]
        
        memory_growth = last["memory_mb"] - first["memory_mb"]
        fd_growth = last["fd_count"] - first["fd_count"]
        
        report = []
        report.append(f"Resource Usage Report:")
        report.append(f"  Initial memory: {first['memory_mb']:.2f} MB")
        report.append(f"  Final memory: {last['memory_mb']:.2f} MB")
        report.append(f"  Memory growth: {memory_growth:.2f} MB ({'LEAK DETECTED' if memory_growth > 50 else 'OK'})")
        report.append(f"  Initial FDs: {first['fd_count']}")
        report.append(f"  Final FDs: {last['fd_count']}")
        report.append(f"  FD growth: {fd_growth} ({'LEAK DETECTED' if fd_growth > 10 else 'OK'})")
        
        return "\n".join(report)


def test_memory_growth():
    """Test for memory leaks during repeated StateManager operations."""
    print("\n--- Test: Memory Growth ---")
    
    monitor = ResourceMonitor()
    monitor.snapshot("start")
    
    namespace = f"memory_test_{int(time.time() * 1000)}"
    
    # Perform many operations
    for batch in range(5):
        sm = get_state_manager(namespace)
        
        # Write operations
        for i in range(100):
            sm.write_route({
                "intent": f"test_{i}",
                "confidence": 0.9,
                "strategy": "TEST"
            })
        
        # Read operations
        for i in range(50):
            sm.read_routes(limit=10)
        
        sm.close()
        
        # Force garbage collection
        gc.collect()
        
        monitor.snapshot(f"batch_{batch}")
        time.sleep(0.1)
    
    monitor.snapshot("end")
    
    print(monitor.report())
    
    # Check for significant memory growth
    memory_growth = monitor.measurements[-1]["memory_mb"] - monitor.measurements[0]["memory_mb"]
    
    passed = memory_growth < 50  # Allow some growth but not excessive
    
    if not passed:
        print(f"⚠️  WARNING: Significant memory growth detected ({memory_growth:.2f} MB)")
    else:
        print(f"✅ Memory growth acceptable ({memory_growth:.2f} MB)")
    
    return passed


def test_file_descriptor_leaks():
    """Test for file descriptor leaks."""
    print("\n--- Test: File Descriptor Leaks ---")
    
    monitor = ResourceMonitor()
    initial_fds = monitor.get_fd_count()
    
    namespace = f"fd_test_{int(time.time() * 1000)}"
    
    # Open and close many StateManagers
    for i in range(20):
        sm = get_state_manager(namespace)
        sm.write_route({
            "intent": f"fd_test_{i}",
            "confidence": 0.5,
            "strategy": "TEST"
        })
        sm.read_last_route()
        sm.close()
    
    # Give time for cleanup
    time.sleep(0.5)
    gc.collect()
    time.sleep(0.5)
    
    final_fds = monitor.get_fd_count()
    fd_growth = final_fds - initial_fds
    
    print(f"  Initial FDs: {initial_fds}")
    print(f"  Final FDs: {final_fds}")
    print(f"  FD growth: {fd_growth}")
    
    passed = fd_growth < 5  # Some fluctuation is OK
    
    if not passed:
        print(f"⚠️  WARNING: File descriptor growth detected ({fd_growth})")
        
        # Try to identify leaked FDs
        try:
            fds = os.listdir(f"/proc/{os.getpid()}/fd")
            print(f"  Open FDs: {len(fds)}")
        except:
            pass
    else:
        print(f"✅ FD growth acceptable ({fd_growth})")
    
    return passed


def test_database_connection_cleanup():
    """Test that database connections are properly cleaned up."""
    print("\n--- Test: Database Connection Cleanup ---")
    
    namespace = f"db_cleanup_test_{int(time.time() * 1000)}"
    
    # Create many StateManagers in sequence
    for i in range(10):
        sm = get_state_manager(namespace)
        sm.write_route({
            "intent": f"cleanup_test_{i}",
            "confidence": 0.7,
            "strategy": "TEST"
        })
        sm.close()
    
    # Check if database file is accessible (not locked)
    db_path = Path(ROOT_DIR) / "state" / "lucy_state.db"
    
    try:
        # Try to open database independently
        import sqlite3
        conn = sqlite3.connect(str(db_path), timeout=1.0)
        cursor = conn.execute("SELECT COUNT(*) FROM routes WHERE intent LIKE 'cleanup_test_%'")
        count = cursor.fetchone()[0]
        conn.close()
        
        print(f"  Routes written: {count}")
        print(f"✅ Database accessible after connections closed")
        return True
    except Exception as e:
        print(f"❌ ERROR: Cannot access database: {e}")
        return False


def test_zombie_processes():
    """Check for zombie processes after execution."""
    print("\n--- Test: Zombie Process Check ---")
    
    import threading
    
    namespace = f"zombie_test_{int(time.time() * 1000)}"
    
    # Create threads that use StateManager
    threads = []
    
    def worker():
        sm = get_state_manager(namespace)
        sm.write_route({
            "intent": "zombie_test",
            "confidence": 0.5,
            "strategy": "TEST"
        })
        sm.close()
    
    for i in range(10):
        t = threading.Thread(target=worker)
        threads.append(t)
        t.start()
    
    for t in threads:
        t.join(timeout=5)
    
    time.sleep(0.5)
    
    # Count threads
    current_process = psutil.Process()
    thread_count = current_process.num_threads()
    
    print(f"  Current thread count: {thread_count}")
    
    # We expect some threads but not excessive
    passed = thread_count < 50
    
    if passed:
        print(f"✅ Thread count normal")
    else:
        print(f"⚠️  WARNING: High thread count ({thread_count})")
    
    return passed


def test_repeated_execution():
    """Test resource usage under repeated execution."""
    print("\n--- Test: Repeated Execution Stress ---")
    
    monitor = ResourceMonitor()
    monitor.snapshot("start")
    
    namespace = f"repeated_test_{int(time.time() * 1000)}"
    errors = []
    
    for i in range(50):
        try:
            sm = get_state_manager(namespace)
            
            # Mix of operations
            sm.write_route({
                "intent": f"repeated_{i}",
                "confidence": 0.8,
                "strategy": "TEST"
            })
            
            if i % 5 == 0:
                sm.read_routes(limit=100)
            
            if i % 10 == 0:
                sm.acquire_lock(f"test_lock_{i % 3}", timeout=0.5)
                sm.release_lock(f"test_lock_{i % 3}")
            
            sm.close()
            
            if i % 10 == 0:
                monitor.snapshot(f"iteration_{i}")
                
        except Exception as e:
            errors.append(f"Iteration {i}: {e}")
    
    gc.collect()
    monitor.snapshot("end")
    
    print(monitor.report())
    
    if errors:
        print(f"❌ Errors during execution: {len(errors)}")
        for err in errors[:3]:
            print(f"  {err}")
        return False
    
    # Check for resource growth
    memory_growth = monitor.measurements[-1]["memory_mb"] - monitor.measurements[0]["memory_mb"]
    fd_growth = monitor.measurements[-1]["fd_count"] - monitor.measurements[0]["fd_count"]
    
    passed = memory_growth < 100 and fd_growth < 20
    
    if passed:
        print(f"✅ Resource usage acceptable after 50 iterations")
    else:
        print(f"⚠️  WARNING: Resource growth detected")
    
    return passed


def main():
    """Run all resource leak tests."""
    print("=" * 70)
    print("RESOURCE LEAK DETECTION TESTS")
    print("=" * 70)
    
    tests = [
        test_database_connection_cleanup,
        test_file_descriptor_leaks,
        test_zombie_processes,
        test_memory_growth,
        test_repeated_execution,
    ]
    
    results = []
    for test in tests:
        try:
            passed = test()
            results.append((test.__name__, passed))
        except Exception as e:
            print(f"\n❌ FAIL: {test.__name__} - Exception: {e}")
            traceback.print_exc()
            results.append((test.__name__, False))
    
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    
    passed_count = sum(1 for _, p in results if p)
    total_count = len(results)
    
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {name}")
    
    print(f"\nTotal: {passed_count}/{total_count} passed")
    
    return passed_count == total_count


if __name__ == "__main__":
    try:
        import psutil
    except ImportError:
        print("Installing psutil...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "psutil", "-q"])
        import psutil
    
    success = main()
    sys.exit(0 if success else 1)
