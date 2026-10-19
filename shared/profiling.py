#!/usr/bin/env python3
"""
shared/profiling.py — Performance Profiling & Execution Tracing Utilities
Enables cProfile tracing on expensive parsing, regex matching, or sync routines.
"""

import cProfile
import pstats
from io import StringIO
from functools import wraps
from typing import Any, Callable, TypeVar
from shared.logging import get_logger

logger = get_logger("profiling")

T = TypeVar("T")


def profile(top_n: int = 10) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator to profile function execution and log cumulative performance hotspots."""
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            profiler = cProfile.Profile()
            profiler.enable()
            try:
                return func(*args, **kwargs)
            finally:
                profiler.disable()
                stream = StringIO()
                stats = pstats.Stats(profiler, stream=stream)
                stats.sort_stats("cumulative")
                stats.print_stats(top_n)
                profile_output = stream.getvalue()
                logger.debug(
                    f"Profile stats for {func.__name__}:\n{profile_output}",
                    extra={"function": func.__name__, "profile": profile_output[:1000]}
                )
        return wrapper
    return decorator
