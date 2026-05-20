"""Token-bucket rate limiter for fair data-source access."""

import time
import threading
from functools import wraps

from ..config import get_config


class TokenBucket:
    """Thread-safe token bucket algorithm."""

    def __init__(self, rate: float, burst: float | None = None):
        self.rate = rate  # tokens per second
        self.capacity = burst or rate * 2
        self._tokens = self.capacity
        self._last_fill = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> bool:
        """Try to consume one token. Returns True if acquired."""
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_fill
            self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
            self._last_fill = now

            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True
            return False

    def wait_and_acquire(self, timeout: float = 10.0) -> bool:
        """Block until a token is available or timeout expires."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.acquire():
                return True
            time.sleep(0.05)
        return False


class RateLimiter:
    """Registry of per-source token buckets."""

    def __init__(self):
        config = get_config()
        self._buckets: dict[str, TokenBucket] = {}
        for source, rate in config.rate_limits.items():
            self._buckets[source] = TokenBucket(rate)

    def acquire(self, source: str, timeout: float = 10.0) -> bool:
        """Acquire a token for the given data source."""
        bucket = self._buckets.get(source)
        if bucket is None:
            return True
        return bucket.wait_and_acquire(timeout)

    def get_bucket(self, source: str) -> TokenBucket | None:
        return self._buckets.get(source)


_limiter: RateLimiter | None = None


def get_limiter() -> RateLimiter:
    global _limiter
    if _limiter is None:
        _limiter = RateLimiter()
    return _limiter


def rate_limit(source: str):
    """Decorator that acquires a rate-limit token before executing the function."""

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            limiter = get_limiter()
            if not limiter.acquire(source):
                from ..exceptions import RateLimitError
                raise RateLimitError(f"Rate limit exceeded for {source}")
            return func(*args, **kwargs)

        return wrapper

    return decorator
