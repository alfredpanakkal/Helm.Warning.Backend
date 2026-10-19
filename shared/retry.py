#!/usr/bin/env python3
"""
shared/retry.py — Retry Decorator with Exponential Backoff and Error Context
Provides resilient retries for network I/O, database queries, and external APIs.
"""

import time
import random
from functools import wraps
from typing import Any, Callable, Tuple, Type, TypeVar
from shared.logging import get_logger

logger = get_logger("retry")

T = TypeVar("T")


def retry(
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    jitter: bool = True,
    exceptions: Tuple[Type[Exception], ...] = (Exception,)
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator applying exponential backoff retry to any function."""
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            last_exception: Exception = RuntimeError("Unexpected retry failure")
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt == max_attempts:
                        logger.error(
                            f"Function {func.__name__} failed on final attempt {attempt}/{max_attempts}: {e}",
                            extra={"func": func.__name__, "attempt": attempt, "error": str(e)}
                        )
                        raise

                    sleep_time = delay * (backoff ** (attempt - 1))
                    if jitter:
                        sleep_time += random.uniform(0, 0.1 * sleep_time)

                    logger.warning(
                        f"Function {func.__name__} failed attempt {attempt}/{max_attempts}: {e}. Retrying in {sleep_time:.2f}s...",
                        extra={"func": func.__name__, "attempt": attempt, "sleep_time": sleep_time}
                    )
                    time.sleep(sleep_time)

            raise last_exception
        return wrapper
    return decorator
