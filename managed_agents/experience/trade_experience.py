"""Trade Experience — 交易评分卡。

记录每笔已平仓交易的完整上下文到 MemoryStore，形成交易员的"经验"。
"""

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from typing import Optional

from ..memory.memory_store import MemoryStore

logger = logging.getLogger(__name__)


@dataclass
class TradeExperience:
    """一笔完整的交易经验（从入场到出场）。"""
    symbol: str
    direction: str          # BUY / SELL
    entry_price: float
    exit_price: float
    volume: int
    pnl: float              # 实际盈亏（元）
    pnl_pct: float          # 盈亏百分比
    strategy: str           # 使用的策略
    signal_type: str        # 信号类型: early_signal / hotspot / manual
    sector: str             # 所属板块
    entry_date: str         # 入场日期
    exit_date: str          # 出场日期
    hold_days: int          # 持股天数
    reason: str             # 入场理由摘要
    market_regime: str = "未知"   # 大盘状态: 牛市/熊市/震荡/未知
    market_change_pct: float = 0.0  # 持有期间大盘涨跌幅
    tags: list[str] = field(default_factory=list)
    created_at: str = ""


def record_experience(exp: TradeExperience) -> bool:
    """将一笔平仓交易写入经验库。

    Args:
        exp: 交易经验对象

    Returns:
        True 写入成功, False 失败
    """
    try:
        store = MemoryStore.get_instance()
        exp.created_at = datetime.now().isoformat(timespec="seconds")
        key = f"trade:{exp.symbol}:{exp.exit_date}"
        tags = [
            f"strategy:{exp.strategy}",
            f"signal:{exp.signal_type}",
            f"sector:{exp.sector}",
            f"result:{'win' if exp.pnl > 0 else 'loss'}",
        ]
        if exp.tags:
            tags.extend(exp.tags)

        store.put(
            key=key,
            value=json.dumps(asdict(exp), ensure_ascii=False),
            tier="experience",
            tags=tags,
        )
        logger.info(f"经验已记录: {key} PnL={exp.pnl:.0f} ({exp.pnl_pct:+.2f}%)")
        return True
    except Exception as e:
        logger.error(f"记录经验失败: {e}")
        return False


def list_experiences(
    strategy: str | None = None,
    symbol: str | None = None,
    result: str | None = None,  # win / loss
    limit: int = 50,
) -> list[dict]:
    """查询历史交易经验。

    Args:
        strategy: 按策略筛选
        symbol: 按股票筛选
        result: win 或 loss
        limit: 最大返回条数
    """
    store = MemoryStore.get_instance()
    entries = store.list_by_tier("experience")
    results = []

    for e in entries:
        try:
            val = json.loads(e["value"])
        except (json.JSONDecodeError, TypeError):
            continue

        if strategy and val.get("strategy") != strategy:
            continue
        if symbol and val.get("symbol") != symbol:
            continue
        if result == "win" and val.get("pnl", 0) <= 0:
            continue
        if result == "loss" and val.get("pnl", 0) >= 0:
            continue

        val["_key"] = e["key"]
        results.append(val)

    return results[:limit]


def experience_stats() -> dict:
    """统计经验库整体指标。"""
    store = MemoryStore.get_instance()
    entries = store.list_by_tier("experience")

    trades = []
    for e in entries:
        try:
            trades.append(json.loads(e["value"]))
        except (json.JSONDecodeError, TypeError):
            continue

    if not trades:
        return {"total_trades": 0}

    wins = [t for t in trades if t.get("pnl", 0) > 0]
    losses = [t for t in trades if t.get("pnl", 0) <= 0]

    # 按策略聚合
    by_strategy: dict[str, dict] = {}
    for t in trades:
        s = t.get("strategy", "未知")
        if s not in by_strategy:
            by_strategy[s] = {"total": 0, "wins": 0, "pnls": []}
        by_strategy[s]["total"] += 1
        by_strategy[s]["pnls"].append(t.get("pnl_pct", 0))
        if t.get("pnl", 0) > 0:
            by_strategy[s]["wins"] += 1

    strategy_stats = {}
    for s, data in by_strategy.items():
        strategy_stats[s] = {
            "total": data["total"],
            "wins": data["wins"],
            "losses": data["total"] - data["wins"],
            "win_rate": round(data["wins"] / data["total"], 2) if data["total"] else 0,
            "avg_pnl_pct": round(sum(data["pnls"]) / len(data["pnls"]), 2) if data["pnls"] else 0,
        }

    return {
        "total_trades": len(trades),
        "total_wins": len(wins),
        "total_losses": len(losses),
        "overall_win_rate": round(len(wins) / len(trades), 2) if trades else 0,
        "total_pnl": round(sum(t.get("pnl", 0) for t in trades), 2),
        "avg_pnl_pct": round(sum(t.get("pnl_pct", 0) for t in trades) / len(trades), 2),
        "by_strategy": strategy_stats,
    }
