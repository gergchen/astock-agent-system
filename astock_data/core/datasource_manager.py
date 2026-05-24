"""Multi-source data manager with fallback, validation, and heartbeat.

Each data source is a callable that takes the same arguments and returns
a pandas DataFrame (or raises a typed exception). The manager tries sources
in priority order, validates output, and falls back on failure.
"""

import logging
import socket
import time
from collections import defaultdict
from typing import Any, Callable

import pandas as pd

from ..config import get_config
from ..exceptions import DataUnavailableError
from .validator import DataValidator

logger = logging.getLogger(__name__)

# 双源交叉验证阈值
_CROSS_VALIDATE_THRESHOLDS = {
    "close_pct": 2.0,    # 收盘价差异超过 2% 报警
    "vol_pct": 50.0,     # 成交量差异超过 50% 报警
}

SourceFunc = Callable[..., pd.DataFrame]


class SourceHealth:
    """Tracks health status of a data source."""

    def __init__(self, name: str, heartbeat_interval: int = 300):
        self.name = name
        self.heartbeat_interval = heartbeat_interval
        self._last_check: float = 0
        self._alive: bool = True
        self._fail_count: int = 0
        self._total_calls: int = 0
        self._total_failures: int = 0

    @property
    def alive(self) -> bool:
        return self._alive

    @property
    def fail_count(self) -> int:
        return self._fail_count

    @property
    def failure_rate(self) -> float:
        if self._total_calls == 0:
            return 0.0
        return self._total_failures / self._total_calls

    def record_success(self):
        self._total_calls += 1
        self._fail_count = 0
        self._alive = True

    def record_failure(self):
        self._total_calls += 1
        self._total_failures += 1
        self._fail_count += 1

    def mark_dead(self):
        self._alive = False


class DataSourceManager:
    """Orchestrates multiple data sources with fallback chain.

    Usage::

        mgr = DataSourceManager()
        mgr.register("mootdx", mootdx_kline_func, priority=0)
        mgr.register("akshare", akshare_kline_func, priority=1)
        mgr.register("tencent", tencent_kline_func, priority=2)

        df = mgr.fetch("600519", category="day", offset=100)
    """

    def __init__(self, validator: DataValidator | None = None):
        self._sources: list[tuple[str, SourceFunc, int]] = []  # (name, func, priority)
        self._health: dict[str, SourceHealth] = {}
        self._validator = validator or DataValidator()
        self._config = get_config()

    def register(self, name: str, func: SourceFunc, priority: int = 0):
        """Register a data source with priority (lower = tried first)."""
        self._sources.append((name, func, priority))
        self._sources.sort(key=lambda x: x[2])
        self._health[name] = SourceHealth(name)

    def unregister(self, name: str):
        self._sources = [(n, f, p) for n, f, p in self._sources if n != name]
        self._health.pop(name, None)

    def get_health(self) -> dict[str, dict]:
        return {
            name: {
                "alive": h.alive,
                "fail_count": h.fail_count,
                "failure_rate": round(h.failure_rate, 3),
            }
            for name, h in self._health.items()
        }

    def _check_tcp(self, host: str, port: int, timeout: float = 5.0) -> bool:
        """TCP connectivity check for a source server."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((host, port))
            sock.close()
            return result == 0
        except Exception:
            return False

    def check_heartbeat(self) -> dict[str, bool]:
        """Run a health check on all registered sources.

        For mootdx, tests TCP connectivity to known TDX servers.
        For HTTP sources, reports based on recent failure history.
        """
        results = {}
        for name, _func, _pri in self._sources:
            health = self._health.get(name)
            if health is None:
                results[name] = False
                continue

            if name == "mootdx":
                alive = False
                for srv in self._config.tdx_servers:
                    if self._check_tcp(srv["ip"], srv["port"]):
                        alive = True
                        break
                if alive:
                    health.record_success()
                else:
                    health.mark_dead()
            else:
                # HTTP sources: alive if no recent consecutive failures
                pass

            results[name] = health.alive
        return results

    def fetch(
        self,
        *args,
        validate: bool = True,
        required_columns: list[str] | None = None,
        positive_columns: list[str] | None = None,
        cross_validate: bool = False,
        **kwargs,
    ) -> pd.DataFrame:
        """Fetch data from sources in priority order with fallback.

        Args:
            *args, **kwargs: Passed directly to each source function.
            validate: Whether to run data validation.
            required_columns: Columns that must be present.
            positive_columns: Columns that must be > 0.
            cross_validate: If True, also try secondary sources and compare.

        Returns:
            Validated DataFrame from the first successful source.

        Raises:
            DataUnavailableError: All sources failed.
        """
        errors = []
        primary_df = None
        primary_name = None
        all_results: list[tuple[str, pd.DataFrame]] = []

        for name, func, _pri in self._sources:
            health = self._health[name]
            if not health.alive and health.fail_count >= 3:
                logger.warning("Skipping dead source: %s", name)
                errors.append(f"{name}: skipped (dead)")
                continue

            try:
                df = func(*args, **kwargs)
            except Exception as e:
                logger.warning("Source '%s' raised: %s", name, e)
                health.record_failure()
                errors.append(f"{name}: {e}")
                continue

            if validate:
                ok, reason = self._validator.validate_dataframe(
                    df, required_columns=required_columns, positive_columns=positive_columns
                )
                if not ok:
                    logger.warning("Source '%s' validation failed: %s", name, reason)
                    health.record_failure()
                    errors.append(f"{name}: validation failed — {reason}")
                    continue

            health.record_success()
            if primary_df is None:
                primary_df = df
                primary_name = name
                logger.info("Data served by: %s", name)
                if not cross_validate:
                    return df  # cross_validate=False → 首次命中即返回

            all_results.append((name, df))

        if primary_df is None:
            raise DataUnavailableError(
                f"All {len(self._sources)} sources failed. Errors: {'; '.join(errors)}"
            )

        # 交叉验证：比对主源与备用源的数据
        if cross_validate and len(all_results) > 1:
            for name, df in all_results[1:]:
                self._cross_validate(primary_name, primary_df, name, df)

        return primary_df

    @staticmethod
    def _cross_validate(
        primary_name: str, primary_df: pd.DataFrame,
        secondary_name: str, secondary_df: pd.DataFrame,
    ):
        """对比两个来源的关键字段，差异超阈值则报警。"""
        if primary_df.empty or secondary_df.empty:
            return

        # 对比收盘价（取最后一条）
        if "close" in primary_df.columns and "close" in secondary_df.columns:
            p_close = float(primary_df["close"].iloc[-1])
            s_close = float(secondary_df["close"].iloc[-1])
            if p_close > 0 and s_close > 0:
                diff = abs(p_close - s_close) / p_close * 100
                if diff > _CROSS_VALIDATE_THRESHOLDS["close_pct"]:
                    logger.warning(
                        "交叉验证: %s 收盘 %.2f vs %s 收盘 %.2f (差异 %.1f%%)",
                        primary_name, p_close, secondary_name, s_close, diff,
                    )

        # 对比成交量
        if "vol" in primary_df.columns and "vol" in secondary_df.columns:
            p_vol = float(primary_df["vol"].iloc[-1])
            s_vol = float(secondary_df["vol"].iloc[-1])
            if p_vol > 0 and s_vol > 0:
                vol_diff = abs(p_vol - s_vol) / max(p_vol, s_vol) * 100
                if vol_diff > _CROSS_VALIDATE_THRESHOLDS["vol_pct"]:
                    logger.warning(
                        "交叉验证: %s 成交量 %.0f vs %s %.0f (差异 %.0f%%)",
                        primary_name, p_vol, secondary_name, s_vol, vol_diff,
                    )

    def fetch_with_timeout(self, timeout: float, *args, **kwargs) -> pd.DataFrame:
        """Fetch with an overall timeout."""
        import threading

        result: list[pd.DataFrame] = []
        error: list[Exception] = []

        def _target():
            try:
                result.append(self.fetch(*args, **kwargs))
            except Exception as e:
                error.append(e)

        t = threading.Thread(target=_target, daemon=True)
        t.start()
        t.join(timeout)
        if t.is_alive():
            raise DataUnavailableError(f"Fetch timed out after {timeout}s")
        if error:
            raise error[0]
        return result[0]
