"""Retry decorator with exponential backoff and jitter."""

import time
import random
from functools import wraps

from ..config import get_config
from ..exceptions import RateLimitError


def _default_retryable() -> tuple:
    """Build default retryable exception set including optional HTTP errors."""
    exc = [ConnectionError, TimeoutError, OSError, RateLimitError]
    try:
        from urllib.error import HTTPError  # urllib
        exc.append(HTTPError)
    except ImportError:
        pass
    try:
        from requests.exceptions import RequestException  # requests
        exc.append(RequestException)
    except ImportError:
        pass
    return tuple(exc)


def retry(
    max_attempts: int | None = None,
    backoff_base: float | None = None,
    jitter: bool | None = None,
    retryable_exceptions: tuple | None = None,
):
    """Decorator: retry on failure with exponential backoff + optional jitter.

    Args:
        max_attempts: Max attempts (default from config).
        backoff_base: Base wait in seconds (default from config).
        jitter: Whether to apply ±25% random jitter (default from config).
        retryable_exceptions: Exception types that trigger a retry.
    """
    config = get_config()
    _max = max_attempts or config.retry_max_attempts
    _base = backoff_base or config.retry_backoff_base
    _jitter = jitter if jitter is not None else config.retry_jitter
    _retryable = retryable_exceptions if retryable_exceptions is not None else _default_retryable()

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(1, _max + 1):
                try:
                    return func(*args, **kwargs)
                except _retryable as e:
                    last_exc = e
                    if attempt == _max:
                        raise
                    wait = _base * (2 ** (attempt - 1))
                    if _jitter:
                        wait *= random.uniform(0.75, 1.25)
                    time.sleep(wait)
            raise last_exc  # pragma: no cover

        return wrapper

    return decorator
