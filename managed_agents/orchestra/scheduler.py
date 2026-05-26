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

from astock_trade.utils.logging_setup import get_logger

from .coordinator import Coordinator
from ..agents.registry import AgentRegistry
from ..utils.notifier import notify, sleep_until_next_session

logger = get_logger(__name__)

# 无效题材关键词 — 过滤无意义分类
_SKIP_SECTORS = {"其他", "其它", "其他板块", "", "综合"}

def _filter_hotspots(hotspots: list[dict]) -> list[dict]:
    """过滤掉无效题材类别."""
    return [h for h in hotspots if h.get("sector", "").strip() not in _SKIP_SECTORS]

_MIN_CONFIDENCE = 0.55  # 相当于≥3只涨停股的板块

def _filter_signals(signals: list[dict]) -> list[dict]:
    """过滤：只保留买入且置信度达标的信号."""
    return [
        s for s in signals
        if s.get("direction") == "BUY"
        and s.get("confidence", 0) >= _MIN_CONFIDENCE
        and s.get("sector", "").strip() not in _SKIP_SECTORS
    ]

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
        notify("调度器下线", "交易时段调度已停止", "info", force=True)
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
                time.sleep(10)
            else:
                # 非交易时段 → 深度休眠到次日盘前，零消耗
                s = sleep_until_next_session()
                if s > 0:
                    logger.info(f"调度器休眠 {s/3600:.1f}h，{datetime.fromtimestamp(time.time() + s).strftime('%m-%d %H:%M')} 唤醒")
                    time.sleep(s)
                else:
                    time.sleep(10)

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
        """盘前: 复盘 + 外围市场 + 题材 + 个股推荐 + 交易策略，合并推送."""
        parts = []

        # 1. 昨日复盘
        try:
            pm = self._registry.get("portfolio-manager")
            recap = pm.post_market_recap()
            if recap.get("success") and recap.get("recap"):
                parts.append(f"📊 昨日复盘\n{recap['recap'][:300]}")
        except KeyError:
            pass

        # 2. 今晨简报（含外围市场、重磅消息、今日关注）
        try:
            analyst = self._registry.get("morning-analyst")
            r = analyst.generate_briefing()
            if r.get("success") and r.get("briefing"):
                parts.append(f"🌙 外围市场 & 盘前简报\n{r['briefing'][:500]}")
        except KeyError:
            pass

        # 3. 研究员题材扫描 + 个股推荐 + 交易策略
        try:
            researcher = self._registry.get("researcher-trader")
            r = researcher.scan_and_generate()
            signals = r.get("signals", [])
            hotspots = _filter_hotspots(r.get("scan", {}).get("hotspots", []))

            # 题材热点
            if hotspots:
                sector_lines = [f"  · {h['sector']}({h.get('count',0)}股)" for h in hotspots[:5]]
                parts.append(f"🔥 今日题材\n" + "\n".join(sector_lines))

            # 早期信号（尚未封板，可操作）
            early_signals = r.get("early_signals", [])
            buy_early = [s for s in early_signals
                         if s.get("direction") == "BUY" and s.get("confidence", 0) >= _MIN_CONFIDENCE]
            if buy_early:
                early_lines = []
                for sig in buy_early[:3]:
                    sector = sig.get("sector", "")
                    conf = sig.get("confidence", 0)
                    stocks = sig.get("actionable_stocks", [])
                    stock_str = "  ".join(f"{s['name']}+{s['gain']}%" for s in stocks[:3])
                    early_lines.append(f"  🟢 {sector} 置信度{conf:.0%}")
                    early_lines.append(f"     {stock_str}")
                parts.append(f"📈 今日关注\n" + "\n".join(early_lines))

            # 原买入信号（已涨停板块，仅作参考）
            buy_signals = _filter_signals(signals)
            if buy_signals and not buy_early:
                rec_lines = []
                for sig in buy_signals[:5]:
                    sector = sig.get("sector", "")
                    conf = sig.get("confidence", 0)
                    count = sig.get("count", 0)
                    rec_lines.append(f"  🟡 {sector} 置信度{conf:.0%} ({count}只涨停)")
                parts.append(f"📈 强势板块\n" + "\n".join(rec_lines))

            # 交易策略（直接让LLM生成策略）
            if hotspots or signals:
                try:
                    from managed_agents.api.client import get_client
                    llm = get_client()
                    hs_text = "\n".join(f"{h['sector']}: {h.get('reason','')[:100]}" for h in hotspots[:5])
                    strategy_prompt = f"基于今日热点题材，给出一份简洁的交易策略（50字以内）：\n{hs_text}"
                    strategy = llm.call([{"role": "user", "content": strategy_prompt}])
                    if strategy:
                        parts.append(f"📝 交易策略\n{strategy[:200]}")
                except Exception:
                    pass
        except KeyError:
            pass

        # 4. 仓位规划
        try:
            pm = self._registry.get("portfolio-manager")
            plan = pm.pre_market_plan()
            if plan.get("success") and plan.get("plan"):
                parts.append(f"💼 仓位规划\n{plan['plan'][:200]}")
        except KeyError:
            pass

        if parts:
            notify("📋 盘前汇总", "\n\n".join(parts), "info", force=True)

    def _execute_session_scan(self) -> None:
        """盘中: ResearcherTrader 扫描 + 信号生成 + 飞书推送."""
        try:
            researcher = self._registry.get("researcher-trader")
            r = researcher.scan_and_generate()
            signals = r.get("signals", [])
            early_signals = r.get("early_signals", [])
            hotspots = _filter_hotspots(r.get("scan", {}).get("hotspots", []))

            # ── 推送早期机会（尚未封板的个股，可操作）──
            pushed_early = False
            if early_signals:
                buy_early = [s for s in early_signals
                             if s.get("direction") == "BUY" and s.get("confidence", 0) >= _MIN_CONFIDENCE]
                if buy_early:
                    lines = [f"⚡ 盘中机会:"]
                    for sig in buy_early[:3]:
                        sector = sig.get("sector", "")
                        conf = sig.get("confidence", 0)
                        stocks = sig.get("actionable_stocks", [])
                        stock_str = "  ".join(f"{s['name']}+{s['gain']}%" for s in stocks[:3])
                        lines.append(f"  🟢 {sector} 置信度{conf:.0%}")
                        lines.append(f"     {stock_str}")
                    notify("盘中机会", "\n".join(lines), "warn", force=True)
                    pushed_early = True
                    logger.info(f"推送早期机会: {len(buy_early)}个板块")

            # ── 原已涨停板块信号（仅在没有早期机会时推送）──
            if signals and not pushed_early:
                buy_signals = _filter_signals(signals)
                if buy_signals:
                    lines = [f"📈 强势板块:"]
                    for sig in buy_signals[:5]:
                        sector = sig.get("sector", "")
                        conf = sig.get("confidence", 0)
                        count = sig.get("count", 0)
                        lines.append(f"  🟡 {sector} {conf:.0%} ({count}只涨停)")
                    notify("盘中机会", "\n".join(lines), "warn", force=True)

            # 有早期信号 → 触发风控审查 + 交易执行
            trade_count = r.get("trade_count", 0)
            if trade_count > 0:
                logger.info(f"自动交易流水线: {trade_count}个交易指令待处理")
                executed = []
                try:
                    risk = self._registry.get("risk-officer")
                    decisions = risk.review_pending()
                    approved = sum(1 for d in decisions if d.get("decision") == "APPROVED")
                    rejected = sum(1 for d in decisions if d.get("decision") == "REJECTED")
                    logger.info(f"风控结果: {approved}批准 {rejected}拒绝")
                except KeyError:
                    logger.warning("风控官未注册")
                    decisions = []

                try:
                    trader = self._registry.get("day-trader")
                    results = trader.execute_pending()
                    success = sum(1 for r in results if r.get("success"))
                    failed = sum(1 for r in results if not r.get("success"))
                    logger.info(f"交易执行: {success}成功 {failed}失败")
                    if results:
                        lines = []
                        for r in results[:5]:
                            if r.get("success"):
                                res = r["result"]
                                lines.append(f"  🟢 {res['symbol']} {res['direction']} {res['price']}x{res['volume']}")
                            elif r.get("error"):
                                dec = r.get("decision", {})
                                sym = (dec.get("signal") or {}).get("symbol", "?")
                                lines.append(f"  🔴 {sym} 失败: {r['error']}")
                        if lines:
                            notify("自动交易执行", "\n".join(lines), "info", force=True)
                            executed = lines
                except KeyError:
                    logger.warning("交易员未注册")

                if not executed:
                    notify("自动交易", f"风控通过{approved}个，但无执行结果", "info", force=True)
            elif early_signals:
                logger.info(f"有早期信号({len(early_signals)}个)但无可执行的交易指令")
                # 仍然触发风控检查（可能有历史信号）
                try:
                    risk = self._registry.get("risk-officer")
                    risk.review_pending()
                except KeyError:
                    pass

            # 发送心跳
            top_sectors = [h["sector"] for h in hotspots[:3]]
            if top_sectors:
                logger.info(f"TOP3板块: {', '.join(top_sectors)} | 信号: {len(signals)}个 | 早期: {len(early_signals)}个")
        except KeyError:
            pass

    def _execute_post_market(self) -> None:
        """盘后: PortfolioManager 复盘（仅存储，不推送，次日盘前统一汇总）."""
        try:
            pm = self._registry.get("portfolio-manager")
            pm.post_market_recap()
        except KeyError:
            pass
