#!/usr/bin/env python3
"""
Tests for resilience.py (circuit breaker).

Run with:
    cd /home/mike/lucy-v8 && source ui-v8/.venv/bin/activate
    python3 -m pytest tools/router_py/test_resilience.py -v
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest

from router_py.resilience import (
    CircuitBreaker,
    CircuitBreakerOpen,
    State,
    get_breaker,
    reset_all_breakers,
    reset_breaker,
)


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------

class TestCircuitBreakerBasics:
    def test_closed_initial_state(self):
        cb = CircuitBreaker("test_closed")
        assert cb.state == State.CLOSED

    def test_success_keeps_closed(self):
        cb = CircuitBreaker("test_success")
        result = cb.call(lambda: "ok")
        assert result == "ok"
        assert cb.state == State.CLOSED

    def test_failure_counts_toward_open(self):
        cb = CircuitBreaker("test_fail", failure_threshold=2, window_seconds=10)
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("fail1")))
        assert cb.state == State.CLOSED  # only 1 failure
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("fail2")))
        assert cb.state == State.OPEN  # threshold reached

    def test_open_raises_fast(self):
        cb = CircuitBreaker("test_open_fast", failure_threshold=1, window_seconds=10)
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("boom")))
        assert cb.state == State.OPEN
        with pytest.raises(CircuitBreakerOpen):
            cb.call(lambda: "should_not_run")

    def test_half_open_after_cooldown(self):
        cb = CircuitBreaker(
            "test_half",
            failure_threshold=1,
            window_seconds=10,
            cooldown_seconds=0.1,
        )
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("boom")))
        assert cb.state == State.OPEN
        time.sleep(0.15)
        # Now the breaker should allow probe requests
        result = cb.call(lambda: "recovery")
        assert result == "recovery"
        assert cb.state == State.CLOSED

    def test_half_open_failure_reopens(self):
        cb = CircuitBreaker(
            "test_reopen",
            failure_threshold=1,
            window_seconds=10,
            cooldown_seconds=0.1,
            probe_requests=1,
        )
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("boom")))
        time.sleep(0.15)
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("boom_again")))
        assert cb.state == State.OPEN

    def test_window_prunes_old_failures(self):
        cb = CircuitBreaker(
            "test_window",
            failure_threshold=3,
            window_seconds=0.2,
            cooldown_seconds=10,
        )
        # 2 failures
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("f1")))
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("f2")))
        assert cb.state == State.CLOSED
        # Wait for window to expire
        time.sleep(0.25)
        # One more failure should NOT open because old ones were pruned
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("f3")))
        assert cb.state == State.CLOSED

    def test_excluded_exceptions_ignored(self):
        cb = CircuitBreaker(
            "test_excluded",
            failure_threshold=1,
            excluded_exceptions=(RuntimeError,),
        )
        with pytest.raises(RuntimeError):
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError("ignored")))
        assert cb.state == State.CLOSED

    def test_not_excluded_exceptions_count(self):
        cb = CircuitBreaker(
            "test_not_excluded",
            failure_threshold=1,
            excluded_exceptions=(RuntimeError,),
        )
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("counts")))
        assert cb.state == State.OPEN


class TestCircuitBreakerConcurrency:
    def test_concurrent_failures(self):
        cb = CircuitBreaker("test_concurrent", failure_threshold=10, window_seconds=10)
        errors = []
        lock = threading.Lock()

        def failer():
            try:
                cb.call(lambda: (_ for _ in ()).throw(ValueError("x")))
            except (ValueError, CircuitBreakerOpen):
                with lock:
                    errors.append(1)

        threads = [threading.Thread(target=failer) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 20
        # After 10 failures the breaker should be OPEN
        assert cb.state in (State.OPEN, State.HALF_OPEN)

    def test_concurrent_mixed_success_failure(self):
        cb = CircuitBreaker("test_mixed", failure_threshold=5, window_seconds=10)
        results = {"ok": 0, "fail": 0, "open": 0}
        lock = threading.Lock()
        counter = [0]

        def worker():
            with lock:
                counter[0] += 1
                should_fail = counter[0] % 2 == 0
            try:
                if should_fail:
                    cb.call(lambda: (_ for _ in ()).throw(ValueError("x")))
                else:
                    cb.call(lambda: "ok")
                with lock:
                    results["ok" if not should_fail else "fail"] += 1
            except CircuitBreakerOpen:
                with lock:
                    results["open"] += 1
            except ValueError:
                with lock:
                    results["fail"] += 1

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert sum(results.values()) == 10


class TestRegistry:
    def test_get_breaker_creates_new(self):
        reset_breaker("test_reg_new")
        cb = get_breaker("test_reg_new")
        assert cb.name == "test_reg_new"

    def test_get_breaker_returns_cached(self):
        reset_breaker("test_reg_cache")
        cb1 = get_breaker("test_reg_cache")
        cb2 = get_breaker("test_reg_cache")
        assert cb1 is cb2

    def test_reset_breaker(self):
        cb1 = get_breaker("test_reg_reset")
        reset_breaker("test_reg_reset")
        cb2 = get_breaker("test_reg_reset")
        assert cb1 is not cb2

    def test_reset_all(self):
        get_breaker("test_reg_a")
        get_breaker("test_reg_b")
        reset_all_breakers()
        cb_a = get_breaker("test_reg_a")
        cb_b = get_breaker("test_reg_b")
        # Should be new instances
        assert cb_a.state == State.CLOSED
        assert cb_b.state == State.CLOSED


class TestDecorator:
    def test_decorator_sync(self):
        reset_breaker("decorated_sync_fn")

        from router_py.resilience import circuit_breaker

        @circuit_breaker("decorated_sync_fn", failure_threshold=1)
        def risky():
            raise ValueError("boom")

        with pytest.raises(ValueError):
            risky()
        with pytest.raises(CircuitBreakerOpen):
            risky()

    def test_decorator_preserves_attrs(self):
        from router_py.resilience import circuit_breaker

        @circuit_breaker()
        def my_func():
            """docstring"""
            return 42

        assert my_func.__name__ == "my_func"
        assert my_func() == 42


# ---------------------------------------------------------------------------
# Async tests
# ---------------------------------------------------------------------------

class TestAsyncCircuitBreaker:
    def test_async_success(self):
        import asyncio

        cb = CircuitBreaker("test_async_ok")

        async def coro():
            return "async_result"

        result = asyncio.run(cb.call_async(coro))
        assert result == "async_result"

    def test_async_failure_opens(self):
        import asyncio

        cb = CircuitBreaker("test_async_fail", failure_threshold=1)

        async def bad():
            raise ValueError("async_boom")

        with pytest.raises(ValueError):
            asyncio.run(cb.call_async(bad))
        assert cb.state == State.OPEN


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
