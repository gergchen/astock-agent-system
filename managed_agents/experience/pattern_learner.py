"""Pattern Learner — 从交易经验中提取模式，反哺决策。

流程:
1. 读取 trade_journal 所有已完成交易
2. FIFO 配对 BUY/SELL 计算实盈实亏
3. 按策略/板块/信号类型/持股天数 聚合胜率
4. 写入 MemoryStore (project tier) 供风控和研究员查询
"""

import json
import logging
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from ..memory.memory_store import MemoryStore

logger = logging.getLogger(__name__)


def compute_roundtrips(
    trades: list[dict],
) -> list[dict]:
    """FIFO 配对同一股票的买卖，计算每笔完整交易的盈亏。

    Args:
        trades: trade_journal 记录列表（含 _date 字段）

    Returns:
        已平仓交易列表，每笔包含 entry/exit 信息和 pnl
    """
    # 按股票分组 + 按时间排序
    by_symbol: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        dt = f"{t.get('_date', '')}T{t.get('timestamp', '')}"
        by_symbol[t["symbol"]].append({**t, "_sort_dt": dt})

    for lst in by_symbol.values():
        lst.sort(key=lambda x: x["_sort_dt"])

    roundtrips = []
    for symbol, txns in by_symbol.items():
        buys: list[dict] = []  # 持仓队列 {volume, price, date}
        for t in txns:
            if t["direction"] == "BUY":
                buys.append({
                    "volume": t["volume"],
                    "price": t["price"],
                    "date": t.get("_date", ""),
                    "strategy": t.get("strategy"),
                    "notes": t.get("notes"),
                })
            elif t["direction"] == "SELL" and buys:
                sell_vol = t["volume"]
                sell_price = t["price"]
                sell_date = t.get("_date", "")
                # FIFO: 从最早的买入开始匹配
                i = 0
                while sell_vol > 0 and i < len(buys):
                    b = buys[i]
                    matched_vol = min(sell_vol, b["volume"])
                    pnl = (sell_price - b["price"]) * matched_vol
                    pnl_pct = (sell_price / b["price"] - 1) * 100
                    hold_days = 1
                    if b["date"] and sell_date:
                        try:
                            bd = date.fromisoformat(b["date"])
                            sd = date.fromisoformat(sell_date)
                            hold_days = (sd - bd).days or 1
                        except ValueError:
                            pass

                    roundtrips.append({
                        "symbol": symbol,
                        "entry_price": b["price"],
                        "exit_price": sell_price,
                        "volume": matched_vol,
                        "pnl": round(pnl, 2),
                        "pnl_pct": round(pnl_pct, 2),
                        "strategy": b.get("strategy"),
                        "sector": _guess_sector(symbol),
                        "entry_date": b["date"],
                        "exit_date": sell_date,
                        "hold_days": hold_days,
                        "reason": b.get("notes", ""),
                    })

                    b["volume"] -= matched_vol
                    sell_vol -= matched_vol
                    i += 1
                # 清理已用完的买单
                buys = [b for b in buys if b["volume"] > 0]

    return roundtrips


def _guess_sector(symbol: str) -> str:
    """根据股票代码前缀推测板块（简单版）。"""
    prefix = symbol[:3]
    sector_map = {
        "600": "主板", "601": "主板", "603": "主板",
        "000": "主板", "001": "主板", "002": "中小板",
        "300": "创业板", "301": "创业板",
        "688": "科创板", "689": "科创板",
        "430": "北交所", "830": "北交所", "833": "北交所", "834": "北交所",
    }
    return sector_map.get(prefix, "未知")


def learn_patterns(roundtrips: list[dict]) -> dict[str, Any]:
    """从回测交易中提取模式，写入 MemoryStore。

    Args:
        roundtrips: compute_roundtrips 的输出

    Returns:
        模式摘要
    """
    if not roundtrips:
        return {"status": "no_data"}

    store = MemoryStore.get_instance()

    def _win_rate(data: list[dict]) -> float:
        if not data:
            return 0
        wins = sum(1 for d in data if d.get("pnl", 0) > 0)
        return round(wins / len(data), 4)

    def _avg_pnl(data: list[dict]) -> float:
        if not data:
            return 0
        return round(sum(d.get("pnl_pct", 0) for d in data) / len(data), 2)

    # ── 按策略聚合 ──
    by_strategy: dict[str, list[dict]] = defaultdict(list)
    for rt in roundtrips:
        s = rt.get("strategy") or "未知"
        by_strategy[s].append(rt)

    for strategy, items in by_strategy.items():
        wins = [d for d in items if d["pnl"] > 0]
        losses = [d for d in items if d["pnl"] <= 0]
        pattern = {
            "type": "strategy_win_rate",
            "strategy": strategy,
            "total": len(items),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": _win_rate(items),
            "avg_pnl_pct": _avg_pnl(items),
            "avg_hold_days": round(sum(d["hold_days"] for d in items) / len(items), 1),
            "total_pnl": round(sum(d["pnl"] for d in items), 2),
            "top_winner": max(items, key=lambda x: x["pnl"]) if items else None,
            "worst_loser": min(items, key=lambda x: x["pnl"]) if items else None,
        }
        store.put(
            key=f"pattern:strategy:{strategy}",
            value=json.dumps(pattern, ensure_ascii=False),
            tier="project",
            tags=["pattern", f"strategy:{strategy}"],
        )

    # ── 按信号类型聚合（从 reason/notes 中提取） ──
    by_signal: dict[str, list[dict]] = defaultdict(list)
    for rt in roundtrips:
        reason = (rt.get("reason") or "").lower()
        strategy = rt.get("strategy") or ""
        if "early" in reason or "early" in strategy:
            by_signal["early_signal"].append(rt)
        elif "hotspot" in reason:
            by_signal["hotspot"].append(rt)
        else:
            by_signal["其他"].append(rt)

    for sig_type, items in by_signal.items():
        store.put(
            key=f"pattern:signal:{sig_type}",
            value=json.dumps({
                "type": "signal_win_rate",
                "signal_type": sig_type,
                "total": len(items),
                "win_rate": _win_rate(items),
                "avg_pnl_pct": _avg_pnl(items),
            }, ensure_ascii=False),
            tier="project",
            tags=["pattern", f"signal:{sig_type}"],
        )

    # ── 按持股天数分类 ──
    short = [d for d in roundtrips if d["hold_days"] <= 3]
    medium = [d for d in roundtrips if 3 < d["hold_days"] <= 10]
    long_ = [d for d in roundtrips if d["hold_days"] > 10]

    for label, items in [("短线(<=3天)", short), ("中线(4-10天)", medium), ("长线(>10天)", long_)]:
        if items:
            store.put(
                key=f"pattern:hold_duration:{label}",
                value=json.dumps({
                    "type": "hold_duration_win_rate",
                    "duration": label,
                    "total": len(items),
                    "win_rate": _win_rate(items),
                    "avg_pnl_pct": _avg_pnl(items),
                }, ensure_ascii=False),
                tier="project",
                tags=["pattern", f"duration:{label}"],
            )

    # ── 整体摘要 ──
    summary = {
        "type": "summary",
        "total_roundtrips": len(roundtrips),
        "overall_win_rate": _win_rate(roundtrips),
        "overall_avg_pnl_pct": _avg_pnl(roundtrips),
        "total_realized_pnl": round(sum(d["pnl"] for d in roundtrips), 2),
        "best_strategy": max(by_strategy, key=lambda s: _win_rate(by_strategy[s])),
        "worst_strategy": min(by_strategy, key=lambda s: _win_rate(by_strategy[s])),
        "analyzed_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "pattern_count": len(by_strategy) + 3,  # strategy + signal + duration
    }
    store.put(
        key="pattern:summary:latest",
        value=json.dumps(summary, ensure_ascii=False),
        tier="project",
        tags=["pattern", "summary"],
    )

    return summary


def run_pattern_analysis(
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict:
    """执行完整模式分析：读取交易流水 → 配对 → 学习 → 写回。

    Args:
        start_date: 起始日期，默认30天前
        end_date: 结束日期，默认今天

    Returns:
        分析摘要
    """
    if end_date is None:
        end_date = date.today()
    if start_date is None:
        start_date = end_date - timedelta(days=30)

    from astock_trade.trade_journal import query_trades
    trades = query_trades(start_date, end_date)
    if not trades:
        return {"status": "no_trades", "period": f"{start_date} ~ {end_date}"}

    roundtrips = compute_roundtrips(trades)
    if not roundtrips:
        return {"status": "no_closed_trades", "total_records": len(trades)}

    summary = learn_patterns(roundtrips)
    summary["period"] = f"{start_date} ~ {end_date}"
    summary["raw_trades"] = len(trades)

    logger.info(
        f"模式分析完成: {len(roundtrips)}笔已平仓交易, "
        f"胜率 {summary.get('overall_win_rate', 0):.0%}, "
        f"总PnL {summary.get('total_realized_pnl', 0):+.0f}"
    )
    return summary


def get_pattern(pattern_key: str) -> dict | None:
    """获取指定模式（供风控/研究员查询）。"""
    store = MemoryStore.get_instance()
    val = store.get(key=pattern_key, tier="project")
    if val:
        try:
            return json.loads(val)
        except (json.JSONDecodeError, TypeError):
            return None
    return None


def get_strategy_win_rate(strategy: str) -> dict | None:
    """查某个策略的历史胜率。"""
    return get_pattern(f"pattern:strategy:{strategy}")


def get_all_patterns() -> dict[str, dict]:
    """列出所有学习到的模式。"""
    store = MemoryStore.get_instance()
    entries = store.list_by_tier("project")
    patterns = {}
    for e in entries:
        if e["key"].startswith("pattern:"):
            try:
                patterns[e["key"]] = json.loads(e["value"])
            except (json.JSONDecodeError, TypeError):
                pass
    return patterns
