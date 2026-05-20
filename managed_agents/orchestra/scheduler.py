"""调度器 — 基于交易时段的定时任务调度.

交易时段 (北京时间):
- 09:00-09:25 — 盘前: MorningAnalyst + PortfolioManager 盘前规划
- 09:30-11:30 — 上午盘: ResearcherTrader 扫描 + DayTrader/RiskOfficer 待命
- 11:30-13:00 — 午休: 中场分析
- 13:00-15:00 — 下午盘: 继续盘中监控
- 15:00-16:00 — 盘后: PortfolioManager 复盘
"""

import functools
import logging
import threading
import time
from datetime import date, datetime, time as dt_time

from .coordinator import Coordinator
from ..agents.registry import AgentRegistry
from ..utils.notifier import notify

logger = logging.getLogger(__name__)

# 交易时段定义
TRADING_SCHEDULE = {
    "pre_market": (dt_time(9, 0), dt_time(9, 25)),
    "morning_session": (dt_time(9, 30), dt_time(11, 30)),
    "lunch_break": (dt_time(11, 30), dt_time(13, 0)),
    "afternoon_session": (dt_time(13, 0), dt_time(15, 0)),
    "post_market": (dt_time(15, 0), dt_time(16, 0)),
}

_trading_calendar_cache: dict[str, list[str]] = {}  # year -> date strings


@functools.lru_cache(maxsize=16)
def is_trading_day(d: date | None = None) -> bool:
    """Check if the given date is an A-stock trading day.

    Uses akshare trading calendar with weekday-only fallback.
    Results are cached by date.
    """
    if d is None:
        d = date.today()

    # Try akshare trading calendar
    year = str(d.year)
    if year not in _trading_calendar_cache:
        try:
            import akshare as ak
            cal_df = ak.tool_trade_date_hist_sina()
            trading_days = cal_df[cal_df["trade_date"].notna()]["trade_date"].astype(str).tolist()
            _trading_calendar_cache[year] = trading_days
        except Exception:
            pass

    if year in _trading_calendar_cache:
        return d.isoformat() in _trading_calendar_cache[year]

    # Fallback: weekday check (no holiday awareness, but better than nothing)
    return d.weekday() < 5


def _get_period(now: dt_time) -> str | None:
    for name, (start, end) in TRADING_SCHEDULE.items():
        if start <= now <= end:
            return name
    return None


class Scheduler:
    """交易时段调度器."""

    def __init__(self, coordinator: Coordinator | None = None):
        self._coordinator = coordinator or Coordinator()
        self._registry = AgentRegistry.get_instance()
        self._running = False
        self._thread: threading.Thread | None = None
        self._last_scans: dict[str, float] = {}
        self._scan_intervals = {
            "pre_market": 300,        # 5 分钟
            "morning_session": 300,   # 5 分钟
            "afternoon_session": 300, # 5 分钟
            "post_market": 3600,      # 仅在收盘后执行一次
        }

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        notify("调度器上线", "交易时段调度已启动", "info")
        logger.info("Scheduler started")

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        notify("调度器下线", "交易时段调度已停止", "info")
        logger.info("Scheduler stopped")

    def _loop(self) -> None:
        today = None  # 跟踪日期，跨日时重置

        while self._running:
            now = datetime.now()
            current_time = now.time()
            current_date = now.date()

            # 新的一天，检查是否需要运行盘前
            if today != current_date:
                today = current_date
                self._last_scans.clear()

            period = _get_period(current_time)
            if period:
                self._check_and_execute(period)

            time.sleep(10)  # 每10秒检查一次

    def _check_and_execute(self, period: str) -> None:
        if not is_trading_day():
            return

        interval = self._scan_intervals.get(period, 300)
        last = self._last_scans.get(period, 0)
        now = time.time()

        if now - last < interval:
            return

        self._last_scans[period] = now
        logger.info(f"Period: {period} — executing scheduled tasks")

        try:
            if period == "pre_market":
                self._execute_pre_market()
            elif period == "morning_session":
                self._execute_session_scan()
            elif period == "afternoon_session":
                self._execute_session_scan()
            elif period == "post_market":
                self._execute_post_market()
        except Exception as e:
            logger.error(f"Scheduled task error [{period}]: {e}")

    def _execute_pre_market(self) -> None:
        """盘前: 复盘昨日 + 今晨简报 + 仓位规划，合并推送."""
        parts = []

        # 1. 昨日复盘
        try:
            pm = self._registry.get("portfolio-manager")
            recap = pm.post_market_recap()
            if recap.get("success") and recap.get("recap"):
                parts.append(f"【昨日复盘】\n{recap['recap'][:300]}")
        except KeyError:
            pass

        # 2. 今晨简报
        try:
            analyst = self._registry.get("morning-analyst")
            r = analyst.generate_briefing()
            if r.get("success") and r.get("briefing"):
                parts.append(f"【今日简报】\n{r['briefing'][:400]}")
        except KeyError:
            pass

        # 3. 仓位规划
        try:
            pm = self._registry.get("portfolio-manager")
            plan = pm.pre_market_plan()
            if plan.get("success") and plan.get("plan"):
                parts.append(f"【仓位规划】\n{plan['plan'][:200]}")
        except KeyError:
            pass

        if parts:
            notify("盘前汇总", "\n\n".join(parts), "info")

    def _execute_session_scan(self) -> None:
        """盘中: ResearcherTrader 扫描 + 信号生成."""
        try:
            researcher = self._registry.get("researcher-trader")
            r = researcher.scan_and_generate()
            signals = r.get("signals", [])

            if signals:
                # 有信号 → 触发风控审查
                try:
                    risk = self._registry.get("risk-officer")
                    risk.review_pending()
                except KeyError:
                    pass

                # 触发交易员执行
                try:
                    trader = self._registry.get("day-trader")
                    trader.execute_pending()
                except KeyError:
                    pass

            # 发送心跳
            hotspots = r.get("scan", {}).get("hotspots", [])
            top_sectors = [h["sector"] for h in hotspots[:3]]
            if top_sectors:
                logger.info(f"TOP3板块: {', '.join(top_sectors)} | 信号: {len(signals)}个")
        except KeyError:
            pass

    def _execute_post_market(self) -> None:
        """盘后: PortfolioManager 复盘（仅存储，不推送，次日盘前统一汇总）."""
        try:
            pm = self._registry.get("portfolio-manager")
            pm.post_market_recap()
        except KeyError:
            pass
