"""SQLite-based data cache with TTL-aware expiration.

Uses WAL mode for concurrent read access. Each cache entry is keyed by
(function_name, args_hash) and stores the JSON-serialized DataFrame with
a creation timestamp and TTL.
"""

import hashlib
import io
import json
import logging
import sqlite3
import time
from datetime import datetime, time as dt_time
from functools import wraps
from pathlib import Path
from threading import Lock

import pandas as pd

from ..config import get_config

logger = logging.getLogger(__name__)

# 盘中缩短 TTL 映射：cache_ttls key -> 盘中 TTL（秒）
_INTRADAY_TTL_OVERRIDE: dict[str, int] = {
    "kline_daily": 60,   # 盘中日 K 1 分钟刷新
    "kline_intraday": 15,  # 盘中分钟线 15 秒刷新
    "valuation": 30,     # 盘中估值 30 秒刷新
}


def _in_trading_hours() -> bool:
    """判断当前是否为 A 股盘中交易时间（9:30-11:30, 13:00-15:00，工作日）。"""
    now = datetime.now()
    if now.weekday() >= 5:  # 周末
        return False
    t = now.time()
    return (dt_time(9, 30) <= t < dt_time(11, 30)) or (dt_time(13, 0) <= t < dt_time(15, 0))

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS cache (
    key       TEXT PRIMARY KEY,
    data      BLOB NOT NULL,
    created   REAL NOT NULL,
    ttl       INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cache_created ON cache(created);
"""


class CacheManager:
    """SQLite-backed cache with WAL mode and automatic expiry."""

    def __init__(self, db_path: str | Path | None = None):
        cfg = get_config()
        db_path = Path(db_path or cfg.cache_dir / "astock_cache.db")
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = str(db_path)
        self._lock = Lock()
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA_SQL)

    def _make_key(self, func_name: str, *args, **kwargs) -> str:
        raw = json.dumps({"args": args, "kwargs": kwargs}, sort_keys=True, default=str)
        digest = hashlib.sha256(raw.encode()).hexdigest()[:32]
        return f"{func_name}:{digest}"

    def get(self, func_name: str, *args, **kwargs) -> pd.DataFrame | None:
        key = self._make_key(func_name, *args, **kwargs)
        with self._lock, sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT data, created, ttl FROM cache WHERE key = ?", (key,)
            ).fetchone()
            if row is None:
                return None
            data_blob, created, ttl = row
            if time.time() - created > ttl:
                conn.execute("DELETE FROM cache WHERE key = ?", (key,))
                return None
            try:
                return pd.read_json(io.StringIO(data_blob), orient="split")
            except Exception:
                conn.execute("DELETE FROM cache WHERE key = ?", (key,))
                return None

    def set(self, func_name: str, df: pd.DataFrame, ttl: int, *args, **kwargs):
        key = self._make_key(func_name, *args, **kwargs)
        data_blob = df.to_json(orient="split", date_format="iso")
        with self._lock, sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO cache (key, data, created, ttl) VALUES (?, ?, ?, ?)",
                (key, data_blob, time.time(), ttl),
            )

    def clear(self):
        with self._lock, sqlite3.connect(self._db_path) as conn:
            conn.execute("DELETE FROM cache")

    def expire(self):
        """Remove all expired entries."""
        with self._lock, sqlite3.connect(self._db_path) as conn:
            conn.execute("DELETE FROM cache WHERE created + ttl < ?", (time.time(),))

    def stats(self) -> dict:
        with self._lock, sqlite3.connect(self._db_path) as conn:
            total = conn.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
            expired = conn.execute(
                "SELECT COUNT(*) FROM cache WHERE created + ttl < ?", (time.time(),)
            ).fetchone()[0]
        return {"total": total, "expired": expired, "active": total - expired}


# Module-level singleton
_cache_mgr: CacheManager | None = None


def get_cache() -> CacheManager:
    global _cache_mgr
    if _cache_mgr is None:
        _cache_mgr = CacheManager()
    return _cache_mgr


def cached(ttl_key: str | None = None, ttl: int | None = None):
    """Decorator: cache DataFrame results with TTL-aware expiration.

    Args:
        ttl_key: Key into config.cache_ttls for TTL lookup (e.g. 'kline_daily').
        ttl: Explicit TTL in seconds (overrides ttl_key).
    """
    cfg = get_config()

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            mgr = get_cache()
            # Resolve TTL
            effective_ttl = ttl
            if effective_ttl is None and ttl_key:
                effective_ttl = cfg.cache_ttls.get(ttl_key, cfg.cache_default_ttl)
            if effective_ttl is None:
                effective_ttl = cfg.cache_default_ttl

            # 盘中交易时段缩短 TTL，保证数据新鲜
            if _in_trading_hours() and ttl_key in _INTRADAY_TTL_OVERRIDE:
                effective_ttl = min(effective_ttl, _INTRADAY_TTL_OVERRIDE[ttl_key])

            # Check cache
            cached_df = mgr.get(func.__name__, *args, **kwargs)
            if cached_df is not None:
                logger.debug("Cache hit: %s", func.__name__)
                return cached_df

            # Miss — fetch and store
            df = func(*args, **kwargs)
            if df is not None and not df.empty:
                mgr.set(func.__name__, df, effective_ttl, *args, **kwargs)
            return df

        return wrapper

    return decorator
