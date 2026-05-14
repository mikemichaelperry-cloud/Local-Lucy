#!/usr/bin/env python3
"""
Circuit breaker for external service calls.

Wraps functions that call external services (Ollama, weather API, time API,
news feeds, Wikipedia, Kimi/OpenAI).  When a service fails repeatedly the
breaker opens and subsequent calls fail fast without hitting the service.

States
------
CLOSED   – normal operation, failures counted
OPEN     – fast-fail for all callers
HALF_OPEN – allow probe_requests to test recovery

Usage
-----
    from router_py.resilience import circuit_breaker, CircuitBreaker

    @circuit_breaker(name="weather_api")
    async def fetch_weather(question: str):
        ...

    # Or manually
    cb = CircuitBreaker(name="ollama", failure_threshold=3, window_seconds=60)
    result = cb.call(my_function, arg1, arg2)
"""

from __future__ import annotations

import functools
import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, TypeVar


logger = logging.getLogger(__name__)

T = TypeVar("T")


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

class State(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


# ---------------------------------------------------------------------------
# Default config
# ---------------------------------------------------------------------------

DEFAULT_FAILURE_THRESHOLD = 3
DEFAULT_WINDOW_SECONDS = 60.0
DEFAULT_COOLDOWN_SECONDS = 30.0
DEFAULT_PROBE_REQUESTS = 1


# ---------------------------------------------------------------------------
# CircuitBreaker
# ---------------------------------------------------------------------------

class CircuitBreaker:
    """
    Thread-safe circuit breaker for a single external service.
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
        window_seconds: float = DEFAULT_WINDOW_SECONDS,
        cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
        probe_requests: int = DEFAULT_PROBE_REQUESTS,
        excluded_exceptions: tuple[type[BaseException], ...] = (),
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.window_seconds = window_seconds
        self.cooldown_seconds = cooldown_seconds
        self.probe_requests = probe_requests
        self.excluded_exceptions = excluded_exceptions

        self._state = State.CLOSED
        self._failure_timestamps: list[float] = []
        self._half_open_probes_remaining = 0
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def state(self) -> State:
        with self._lock:
            return self._state

    def call(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """
        Synchronous call through the breaker.

        Raises CircuitBreakerOpen if the breaker is OPEN.
        """
        self._before_call()
        try:
            result = fn(*args, **kwargs)
            self._on_success()
            return result
        except BaseException as exc:
            self._on_failure(exc)
            raise

    async def call_async(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """
        Asynchronous call through the breaker.

        Raises CircuitBreakerOpen if the breaker is OPEN.
        """
        self._before_call()
        try:
            if asyncio.iscoroutinefunction(fn):
                result = await fn(*args, **kwargs)
            else:
                result = fn(*args, **kwargs)
            self._on_success()
            return result
        except BaseException as exc:
            self._on_failure(exc)
            raise

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------

    def _before_call(self) -> None:
        with self._lock:
            self._prune_old_failures()

            if self._state == State.OPEN:
                if self._cooldown_expired():
                    self._transition_to(State.HALF_OPEN)
                    self._half_open_probes_remaining = self.probe_requests
                else:
                    raise CircuitBreakerOpen(self.name)

            if self._state == State.HALF_OPEN:
                if self._half_open_probes_remaining <= 0:
                    raise CircuitBreakerOpen(self.name)
                # Will decrement after the call outcome is known

    def _on_success(self) -> None:
        with self._lock:
            if self._state == State.HALF_OPEN:
                self._half_open_probes_remaining -= 1
                if self._half_open_probes_remaining <= 0:
                    self._transition_to(State.CLOSED)
                    self._failure_timestamps.clear()
            elif self._state == State.CLOSED:
                # Optional: could track successes, but we only count failures
                pass

    def _on_failure(self, exc: BaseException) -> None:
        with self._lock:
            # Excluded exceptions don't count toward breaker
            if self.excluded_exceptions and isinstance(exc, self.excluded_exceptions):
                return

            now = time.monotonic()

            if self._state == State.HALF_OPEN:
                self._half_open_probes_remaining -= 1
                self._failure_timestamps.append(now)
                self._transition_to(State.OPEN)
                return

            if self._state == State.CLOSED:
                self._failure_timestamps.append(now)
                self._prune_old_failures()
                if len(self._failure_timestamps) >= self.failure_threshold:
                    self._transition_to(State.OPEN)

    def _transition_to(self, new_state: State) -> None:
        old_state = self._state
        if old_state == new_state:
            return
        self._state = new_state
        logger.warning(
            "circuit_breaker_state_change",
            extra={
                "breaker_name": self.name,
                "old_state": old_state.value,
                "new_state": new_state.value,
                "failures_in_window": len(self._failure_timestamps),
            },
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _prune_old_failures(self) -> None:
        cutoff = time.monotonic() - self.window_seconds
        self._failure_timestamps = [t for t in self._failure_timestamps if t >= cutoff]

    def _cooldown_expired(self) -> bool:
        # We don't track the exact open time; we use the last failure timestamp
        if not self._failure_timestamps:
            return True
        last_failure = max(self._failure_timestamps)
        return time.monotonic() - last_failure >= self.cooldown_seconds


class CircuitBreakerOpen(Exception):
    """Raised when a call is made while the circuit breaker is OPEN."""

    def __init__(self, breaker_name: str) -> None:
        self.breaker_name = breaker_name
        super().__init__(f"Circuit breaker '{breaker_name}' is OPEN")


# ---------------------------------------------------------------------------
# Registry (global breakers keyed by name)
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, CircuitBreaker] = {}
_REGISTRY_LOCK = threading.Lock()


def get_breaker(
    name: str,
    failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
    window_seconds: float = DEFAULT_WINDOW_SECONDS,
    cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
    probe_requests: int = DEFAULT_PROBE_REQUESTS,
) -> CircuitBreaker:
    """Get or create a named circuit breaker."""
    with _REGISTRY_LOCK:
        if name not in _REGISTRY:
            _REGISTRY[name] = CircuitBreaker(
                name=name,
                failure_threshold=failure_threshold,
                window_seconds=window_seconds,
                cooldown_seconds=cooldown_seconds,
                probe_requests=probe_requests,
            )
        return _REGISTRY[name]


def reset_breaker(name: str) -> None:
    """Remove a breaker from the registry (useful for tests)."""
    with _REGISTRY_LOCK:
        _REGISTRY.pop(name, None)


def reset_all_breakers() -> None:
    """Clear the entire breaker registry."""
    with _REGISTRY_LOCK:
        _REGISTRY.clear()


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------

def circuit_breaker(
    name: str | None = None,
    failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
    window_seconds: float = DEFAULT_WINDOW_SECONDS,
    cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
    probe_requests: int = DEFAULT_PROBE_REQUESTS,
) -> Callable:
    """Decorator that wraps a function in a circuit breaker."""
    def decorator(fn: Callable) -> Callable:
        breaker_name = name or fn.__qualname__
        cb = get_breaker(
            breaker_name,
            failure_threshold=failure_threshold,
            window_seconds=window_seconds,
            cooldown_seconds=cooldown_seconds,
            probe_requests=probe_requests,
        )

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return cb.call(fn, *args, **kwargs)

        @functools.wraps(fn)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            return await cb.call_async(fn, *args, **kwargs)

        # Attach breaker for introspection
        wrapper._circuit_breaker = cb  # type: ignore[attr-defined]
        async_wrapper._circuit_breaker = cb  # type: ignore[attr-defined]

        if asyncio.iscoroutinefunction(fn):
            return async_wrapper
        return wrapper
    return decorator


# We need asyncio for the decorator check
import asyncio
