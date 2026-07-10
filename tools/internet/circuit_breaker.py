#!/usr/bin/env python3
"""Circuit breaker for external HTTP backends.

Tracks consecutive failures per backend and skips unhealthy backends
for a cooldown period to avoid blocking queries with repeated timeouts.

Thread-safe. In-memory only (resets on process restart).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable, Tuple, TypeVar, Union


@dataclass
class _BackendState:
    failures: int = 0
    last_failure: float = 0.0
    open_since: float | None = None


_T = TypeVar("_T")


class CircuitBreaker:
    """Simple failure-count circuit breaker.

    Args:
        failure_threshold: consecutive failures before opening
        cooldown_sec: seconds to skip the backend after opening
    """

    def __init__(self, failure_threshold: int = 3, cooldown_sec: float = 300.0) -> None:
        self.failure_threshold = failure_threshold
        self.cooldown_sec = cooldown_sec
        self._states: dict[str, _BackendState] = {}
        self._lock = threading.Lock()

    def is_open(self, backend: str) -> bool:
        with self._lock:
            state = self._states.get(backend)
            if state is None or state.open_since is None:
                return False
            if time.time() - state.open_since >= self.cooldown_sec:
                # Auto-close after cooldown
                state.open_since = None
                state.failures = 0
                return False
            return True

    def record_success(self, backend: str) -> None:
        with self._lock:
            state = self._states.get(backend)
            if state is None:
                return
            state.failures = 0
            state.open_since = None

    def record_failure(self, backend: str) -> None:
        with self._lock:
            state = self._states.setdefault(backend, _BackendState())
            state.failures += 1
            state.last_failure = time.time()
            if state.failures >= self.failure_threshold:
                state.open_since = time.time()

    def call(self, backend: str, fn: Callable[[], _T]) -> Tuple[bool, Union[_T, str]]:
        """Execute fn if backend is closed; return (success, result_or_reason)."""
        if self.is_open(backend):
            return False, f"circuit_open: {backend} cooling down"
        try:
            result = fn()
            self.record_success(backend)
            return True, result
        except Exception as exc:
            self.record_failure(backend)
            return False, str(exc)
