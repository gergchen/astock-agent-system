# 指标买卖信号阈值检测
# 移植自 InStock 的 guess_buy / guess_sell 逻辑

import logging

from astock_data.ta.config import BUY_SIGNALS, SELL_SIGNALS

logger = logging.getLogger(__name__)

# ── 比较操作 ──────────────────────────────────

def _check(operator: str, value: float, threshold: float) -> bool:
    if operator == ">=":
        return value >= threshold
    elif operator == "<":
        return value < threshold
    elif operator == ">":
        return value > threshold
    elif operator == "<=":
        return value <= threshold
    elif operator == "==":
        return abs(value - threshold) < 1e-9
    return False


# ── 公开函数 ──────────────────────────────────

def get_buy_signals(indicators: dict) -> list[str]:
    """根据指标阈值判断买入信号。

    Args:
        indicators: {指标名: 值} 字典（来自 get_latest_indicators）。

    Returns:
        触发的买入信号名列表，如 ["KDJ超买", "RSI超买"]。
    """
    signals = []
    for key, rule in BUY_SIGNALS.items():
        val = indicators.get(key)
        if val is not None and _check(rule["op"], float(val), rule["value"]):
            signals.append(key)
    return signals


def get_sell_signals(indicators: dict) -> list[str]:
    """根据指标阈值判断卖出信号。"""
    signals = []
    for key, rule in SELL_SIGNALS.items():
        val = indicators.get(key)
        if val is not None and _check(rule["op"], float(val), rule["value"]):
            signals.append(key)
    return signals


def get_technical_signals(indicators: dict) -> dict:
    """综合返回买卖信号。

    Returns:
        {"buy": [...], "sell": [...]}
    """
    return {
        "buy": get_buy_signals(indicators),
        "sell": get_sell_signals(indicators),
    }
