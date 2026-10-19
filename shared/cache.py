#!/usr/bin/env python3
"""
shared/cache.py — Thread-Safe Caching Layer with TTL & Optional Redis Backend
Caches expensive HTTP responses, AI coordinate groundings, and parsing outcomes.
"""

import time
import json
import hashlib
import threading
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Callable, Dict, Optional, Tuple
from shared.logging import get_logger
from shared.metrics import metrics

logger = get_logger("cache")


@dataclass
class CacheEntry:
    value: Any
    expires_at: float
    created_at: float = field(default_factory=time.time)

    def is_expired(self) -> bool:
        return time.time() > self.expires_at


class InMemoryCache:
    """Thread-safe in-memory cache with TTL support and size limits."""

    def __init__(self, default_ttl: float = 300.0, max_size: int = 5000):
        self._store: Dict[str, CacheEntry] = {}
        self._lock = threading.Lock()
        self.default_ttl = default_ttl
        self.max_size = max_size

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            entry = self._store.get(key)
            if entry is not None:
                if not entry.is_expired():
                    metrics.counter("cache_hits_total", labels={"backend": "memory"}).increment()
                    return entry.value
                else:
                    del self._store[key]
            metrics.counter("cache_misses_total", labels={"backend": "memory"}).increment()
            return None

    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        with self._lock:
            # Enforce max size limit by purging oldest entries
            if len(self._store) >= self.max_size:
                self._purge_oldest(int(self.max_size * 0.1) + 1)

            effective_ttl = ttl if ttl is not None else self.default_ttl
            self._store[key] = CacheEntry(
                value=value,
                expires_at=time.time() + effective_ttl
            )

    def delete(self, key: str) -> bool:
        with self._lock:
            if key in self._store:
                del self._store[key]
                return True
            return False

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def cleanup_expired(self) -> int:
        with self._lock:
            now = time.time()
            expired_keys = [k for k, entry in self._store.items() if now > entry.expires_at]
            for k in expired_keys:
                del self._store[k]
            return len(expired_keys)

    def _purge_oldest(self, count: int) -> None:
        sorted_keys = sorted(self._store.keys(), key=lambda k: self._store[k].created_at)
        for k in sorted_keys[:count]:
            del self._store[k]

    def size(self) -> int:
        with self._lock:
            return len(self._store)


class RedisCache:
    """Optional Redis cache client with automatic serialization."""

    def __init__(self, host: str = "localhost", port: int = 6379, db: int = 0, default_ttl: float = 300.0):
        self.host = host
        self.port = port
        self.db = db
        self.default_ttl = int(default_ttl)
        self.client = None
        self._connected = False
        self._init_client()

    def _init_client(self):
        try:
            import redis
            self.client = redis.Redis(host=self.host, port=self.port, db=self.db, socket_timeout=3.0)
            self.client.ping()
            self._connected = True
            logger.info(f"Connected to Redis cache at {self.host}:{self.port}/{self.db}")
        except Exception as e:
            logger.warning(f"Redis cache unavailable ({e}), falling back to memory cache.")
            self._connected = False

    def get(self, key: str) -> Optional[Any]:
        if not self._connected or not self.client:
            return None
        try:
            val = self.client.get(key)
            if val is not None:
                metrics.counter("cache_hits_total", labels={"backend": "redis"}).increment()
                return json.loads(val.decode("utf-8"))
            metrics.counter("cache_misses_total", labels={"backend": "redis"}).increment()
            return None
        except Exception as e:
            logger.warning(f"Redis get failed for {key}: {e}")
            return None

    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        if not self._connected or not self.client:
            return
        try:
            data = json.dumps(value, ensure_ascii=False)
            effective_ttl = int(ttl) if ttl is not None else self.default_ttl
            self.client.setex(key, effective_ttl, data)
        except Exception as e:
            logger.warning(f"Redis set failed for {key}: {e}")

    def delete(self, key: str) -> bool:
        if not self._connected or not self.client:
            return False
        try:
            return bool(self.client.delete(key))
        except Exception:
            return False

    def clear(self) -> None:
        if self._connected and self.client:
            try:
                self.client.flushdb()
            except Exception:
                pass


# Global Cache Instance (Memory by default, Redis if REDIS_HOST set)
cache = InMemoryCache(default_ttl=300.0)


def initialize_cache(redis_host: Optional[str] = None, redis_port: int = 6379) -> None:
    """Initializes global cache instance with Redis if host specified."""
    global cache
    if redis_host:
        redis_c = RedisCache(host=redis_host, port=redis_port)
        if redis_c._connected:
            cache = redis_c
            return
    cache = InMemoryCache()


def cached(
    ttl: Optional[float] = None,
    key_func: Optional[Callable[..., str]] = None
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator to cache function return values."""
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if key_func:
                cache_key = key_func(*args, **kwargs)
            else:
                arg_repr = repr(args) + repr(sorted(kwargs.items()))
                cache_key = f"{func.__module__}:{func.__name__}:{hashlib.sha256(arg_repr.encode('utf-8')).hexdigest()}"

            cached_val = cache.get(cache_key)
            if cached_val is not None:
                return cached_val

            result = func(*args, **kwargs)
            cache.set(cache_key, result, ttl=ttl)
            return result
        return wrapper
    return decorator
