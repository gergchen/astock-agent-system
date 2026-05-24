import time
import logging

logger = logging.getLogger(__name__)

SWEEP_INTERVAL = 60


class MessageDedup:
    """Map + TTL dedup, prevents duplicate processing on WS reconnect."""

    def __init__(self, ttl: float = 600, max_entries: int = 5000):
        self._ttl = ttl
        self._max = max_entries
        self._store: dict[str, float] = {}
        self._last_sweep = time.time()

    def try_record(self, key: str) -> bool:
        """Return True if new, False if duplicate."""
        self._maybe_sweep()
        now = time.time()

        existing = self._store.get(key)
        if existing is not None and now - existing < self._ttl:
            return False

        if len(self._store) >= self._max:
            oldest = next(iter(self._store))
            del self._store[oldest]

        self._store[key] = now
        return True

    def _maybe_sweep(self) -> None:
        now = time.time()
        if now - self._last_sweep < SWEEP_INTERVAL:
            return
        self._last_sweep = now
        cutoff = now - self._ttl
        expired = [k for k, ts in self._store.items() if ts < cutoff]
        for k in expired:
            del self._store[k]
        if expired:
            logger.debug("Dedup sweep: removed %d expired entries", len(expired))

    def clear(self) -> None:
        self._store.clear()
