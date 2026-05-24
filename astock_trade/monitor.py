"""System health aggregator — gathers status across all subsystems.

No LLM dependency — pure read-only inspection of running state.
"""

import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .config import get_config as get_trade_config

logger = logging.getLogger(__name__)

_START_TIME = time.time()


def _uptime_sec() -> float:
    return time.time() - _START_TIME


# ── Dataclasses ────────────────────────────────────────────────────


@dataclass
class SubsystemHealth:
    name: str
    status: str  # "ok" | "degraded" | "down" | "unknown"
    detail: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass
class SystemHealth:
    subsystems: list[SubsystemHealth] = field(default_factory=list)
    overall: str = "unknown"
    uptime_sec: float = 0
    memory_mb: float = 0
    checked_at: str = ""

    @property
    def ok_count(self) -> int:
        return sum(1 for s in self.subsystems if s.status == "ok")

    @property
    def degraded_count(self) -> int:
        return sum(1 for s in self.subsystems if s.status == "degraded")

    @property
    def down_count(self) -> int:
        return sum(1 for s in self.subsystems if s.status == "down")


# ── Subsystem checks ───────────────────────────────────────────────


def _check_directories() -> SubsystemHealth:
    cfg = get_trade_config()
    dirs = {
        "data": cfg.data_dir,
        "journal": cfg.trade_journal_dir,
        "strategies": cfg.strategies_dir,
        "watchlists": cfg.watchlists_dir,
        "alerts": cfg.alerts_dir,
        "bus": cfg.bus_dir,
    }
    missing = [name for name, d in dirs.items() if not d.exists()]
    if missing:
        return SubsystemHealth("directories", "degraded", f"Missing: {', '.join(missing)}")
    return SubsystemHealth("directories", "ok", f"{len(dirs)} dirs present")


def _check_data_sources() -> SubsystemHealth:
    try:
        from astock_data.core.datasource_manager import DataSourceManager

        mgr = DataSourceManager()
        health = mgr.get_health()
        if not health:
            return SubsystemHealth("data_sources", "ok", "no sources registered")
        alive = [k for k, v in health.items() if v.get("alive")]
        dead = [k for k, v in health.items() if not v.get("alive")]
        metrics = {"total": len(health), "alive": alive, "dead": dead}
        if dead and not alive:
            return SubsystemHealth("data_sources", "down", f"All dead: {dead}", metrics)
        if dead:
            return SubsystemHealth("data_sources", "degraded", f"Dead: {dead}", metrics)
        return SubsystemHealth("data_sources", "ok", f"{len(alive)} alive", metrics)
    except Exception as e:
        return SubsystemHealth("data_sources", "unknown", str(e))


def _check_signal_bus() -> SubsystemHealth:
    try:
        from .signal_bus import SignalBus

        bus = SignalBus()
        stats = bus.stats()
        failed = stats.get("failed", 0)
        status = "degraded" if failed > 10 else "ok"
        return SubsystemHealth("signal_bus", status, "", {
            "pending": stats.get("pending", 0),
            "processing": stats.get("processing", 0),
            "processed": stats.get("processed", 0),
            "failed": failed,
        })
    except Exception as e:
        return SubsystemHealth("signal_bus", "unknown", str(e))


def _check_cache() -> SubsystemHealth:
    try:
        from astock_data.core.cache import CacheManager

        cache = CacheManager()
        stats = cache.stats()
        expired = stats.get("expired", 0)
        total = stats.get("total", 0)
        status = "degraded" if expired > total * 0.5 and total > 0 else "ok"
        return SubsystemHealth("cache", status, "", stats)
    except Exception as e:
        return SubsystemHealth("cache", "unknown", str(e))


def _check_process() -> SubsystemHealth:
    info: dict[str, Any] = {"pid": os.getpid()}
    try:
        import psutil

        proc = psutil.Process()
        mem = proc.memory_info()
        info["memory_rss_mb"] = round(mem.rss / 1024 / 1024, 1)
        info["memory_vms_mb"] = round(mem.vms / 1024 / 1024, 1)
        info["cpu_pct"] = round(proc.cpu_percent(interval=0.1), 1)
        info["threads"] = proc.num_threads()
        info["open_files"] = len(proc.open_files())

        if info["open_files"] > 500:
            return SubsystemHealth("process", "degraded", f"ulimit high: {info['open_files']} open files", info)
        if info["memory_rss_mb"] > 2000:
            return SubsystemHealth("process", "degraded", f"High memory: {info['memory_rss_mb']} MB", info)
        return SubsystemHealth("process", "ok", "", info)
    except ImportError:
        info["memory_rss_mb"] = -1
        return SubsystemHealth("process", "ok", "psutil not installed", info)
    except Exception as e:
        return SubsystemHealth("process", "unknown", str(e), {"pid": os.getpid()})


def _check_alerts() -> SubsystemHealth:
    try:
        from .utils.alerting import FileAlertChannel

        ch = FileAlertChannel()
        recent = ch.history(20)
        critical = [a for a in recent if a.get("level") == "critical"]
        status = "degraded" if len(critical) > 0 else "ok"
        return SubsystemHealth("alerts", status, "", {
            "total_recent": len(recent),
            "critical_count": len(critical),
            "latest_ts": recent[0]["ts"] if recent else "none",
        })
    except Exception as e:
        return SubsystemHealth("alerts", "unknown", str(e))


def _check_backtest_data() -> SubsystemHealth:
    try:
        data_dir = Path("data/backtest")
        if not data_dir.exists():
            return SubsystemHealth("backtest_data", "degraded", "data/backtest/ missing")
        files = list(data_dir.glob("*.csv"))
        if not files:
            return SubsystemHealth("backtest_data", "degraded", "No CSV files found")
        return SubsystemHealth("backtest_data", "ok", f"{len(files)} CSVs", {"file_count": len(files)})
    except Exception as e:
        return SubsystemHealth("backtest_data", "unknown", str(e))


# ── Aggregator ─────────────────────────────────────────────────────


def check_all() -> SystemHealth:
    """Run all subsystem checks and return aggregated SystemHealth."""
    subs = [
        _check_directories(),
        _check_process(),
        _check_data_sources(),
        _check_signal_bus(),
        _check_cache(),
        _check_alerts(),
        _check_backtest_data(),
    ]

    statuses = {s.status for s in subs}
    if "down" in statuses:
        overall = "degraded"
    elif "degraded" in statuses or "unknown" in statuses:
        overall = "degraded"
    else:
        overall = "ok"

    mem = 0.0
    for s in subs:
        if s.name == "process" and s.metrics:
            mem = s.metrics.get("memory_rss_mb", 0)

    return SystemHealth(
        subsystems=subs,
        overall=overall,
        uptime_sec=_uptime_sec(),
        memory_mb=mem,
        checked_at=datetime.now().isoformat(),
    )


def health_summary() -> str:
    """One-line health summary for quick status."""
    h = check_all()
    return (
        f"[{h.overall.upper()}] uptime={h.uptime_sec/3600:.1f}h "
        f"mem={h.memory_mb:.0f}MB "
        f"ok={h.ok_count}/{len(h.subsystems)}"
    )
