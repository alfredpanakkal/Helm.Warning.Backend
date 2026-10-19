#!/usr/bin/env python3
"""
shared/circuit_breaker.py — Circuit Breaker Pattern for External Integrations
Prevents cascading failures and catastrophic latency on flaky external services (Supabase, Gemini API, Web Scrapers).
"""

import time
import threading
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Callable, Dict, Optional, TypeVar
from shared.exceptions import CircuitBreakerError, CircuitBreakerOpenError
from shared.logging import get_logger
from shared.metrics import metrics

logger = get_logger("circuit_breaker")

T = TypeVar("T")


@dataclass
class CircuitBreakerState:
    failures: int = 0
    successes: int = 0
    last_failure_time: float = 0.0
    last_success_time: float = 0.0
    state: str = "CLOSED"  # "CLOSED", "OPEN", "HALF_OPEN"


class CircuitBreaker:
    """Thread-safe circuit breaker implementation."""

    def __init__(
        self,
        name: str = "default",
        max_failures: int = 5,
        reset_timeout: float = 30.0,
        half_open_max_attempts: int = 3,
    ):
        self.name = name
        self.max_failures = max_failures
        self.reset_timeout = reset_timeout
        self.half_open_max_attempts = half_open_max_attempts
        self._state = CircuitBreakerState()
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        with self._lock:
            # Check for automatic transition from OPEN to HALF_OPEN
            if self._state.state == "OPEN":
                if time.time() - self._state.last_failure_time > self.reset_timeout:
                    self._state.state = "HALF_OPEN"
                    self._state.failures = 0
                    self._state.successes = 0
                    logger.info(f"CircuitBreaker '{self.name}' transitioning from OPEN to HALF_OPEN")
            return self._state.state

    def call(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Executes a callable through the circuit breaker gate."""
        current_state = self.state

        if current_state == "OPEN":
            remaining = self.reset_timeout - (time.time() - self._state.last_failure_time)
            metrics.counter("circuit_breaker_rejections_total", labels={"name": self.name}).increment()
            raise CircuitBreakerOpenError(
                f"CircuitBreaker '{self.name}' is OPEN. Rejection active for {max(0.0, remaining):.1f}s.",
                context={"name": self.name, "reset_timeout": self.reset_timeout, "remaining": remaining}
            )

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure(e)
            raise

    def _on_success(self) -> None:
        with self._lock:
            self._state.last_success_time = time.time()
            if self._state.state == "HALF_OPEN":
                self._state.successes += 1
                if self._state.successes >= self.half_open_max_attempts:
                    self._state.state = "CLOSED"
                    self._state.failures = 0
                    logger.info(f"CircuitBreaker '{self.name}' successfully recovered to CLOSED.")
            elif self._state.state == "CLOSED":
                self._state.failures = 0

    def _on_failure(self, exc: Exception) -> None:
        with self._lock:
            self._state.failures += 1
            self._state.last_failure_time = time.time()
            metrics.counter("circuit_breaker_failures_total", labels={"name": self.name}).increment()

            if self._state.state == "HALF_OPEN":
                self._state.state = "OPEN"
                logger.warning(f"CircuitBreaker '{self.name}' tripped back to OPEN after test failure: {exc}")
            elif self._state.state == "CLOSED" and self._state.failures >= self.max_failures:
                self._state.state = "OPEN"
                logger.warning(
                    f"CircuitBreaker '{self.name}' tripped to OPEN after {self._state.failures} consecutive failures. "
                    f"Reset timeout: {self.reset_timeout}s. Last error: {exc}"
                )

    def reset(self) -> None:
        with self._lock:
            self._state.state = "CLOSED"
            self._state.failures = 0
            self._state.successes = 0


# Global Registry of Breakers
_breakers: Dict[str, CircuitBreaker] = {}
_breakers_lock = threading.Lock()


def get_circuit_breaker(
    name: str,
    max_failures: int = 5,
    reset_timeout: float = 30.0,
    half_open_max_attempts: int = 3
) -> CircuitBreaker:
    with _breakers_lock:
        if name not in _breakers:
            _breakers[name] = CircuitBreaker(
                name=name,
                max_failures=max_failures,
                reset_timeout=reset_timeout,
                half_open_max_attempts=half_open_max_attempts
            )
        return _breakers[name]


def circuit_breaker(
    name: str,
    max_failures: int = 5,
    reset_timeout: float = 30.0,
    half_open_max_attempts: int = 3
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator to apply circuit breaker protection to any function."""
    breaker = get_circuit_breaker(name, max_failures, reset_timeout, half_open_max_attempts)

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            return breaker.call(func, *args, **kwargs)
        return wrapper
    return decorator
