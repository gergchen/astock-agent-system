"""事件总线 — Agent 间发布/订阅通信.

直接复用 astock_trade 的 bus 模块（publish/consume/peek），
增加内存级事件回调机制，支持实时推送告警。
"""

import logging
from typing import Callable

from astock_trade import bus as _trade_bus

logger = logging.getLogger(__name__)

# 回调订阅者: {channel: [callback]}
_subscribers: dict[str, list[Callable]] = {}


class EventBus:
    """事件总线 — 桥接 astock_trade 文件总线 + 内存回调."""

    CHANNELS = {
        "from_researcher": "研究员 → 风控官 (交易信号)",
        "from_risk_officer": "风控官 → 交易员 (审批结果)",
        "from_trader": "交易员 → 所有人 (交易结果)",
        "portfolio_plan": "操盘手 → 研究员 (仓位计划)",
        "alerts": "任何人 → 用户 (告警)",
        "status": "心跳/状态更新",
    }

    @staticmethod
    def publish(channel: str, message: dict) -> str:
        """发布消息到指定频道."""
        # 写入文件总线
        path = _trade_bus.publish(channel, message)

        # 触发内存回调
        for cb in _subscribers.get(channel, []):
            try:
                cb(channel, message)
            except Exception as e:
                logger.error(f"Callback error on {channel}: {e}")

        # 也触发 '*' 通配订阅者
        for cb in _subscribers.get("*", []):
            try:
                cb(channel, message)
            except Exception as e:
                logger.error(f"Wildcard callback error: {e}")

        return str(path)

    @staticmethod
    def consume(channel: str, n: int = 1) -> list[dict]:
        """消费（读取并移除）消息."""
        return _trade_bus.consume(channel, n)

    @staticmethod
    def peek(channel: str, limit: int = 10) -> list[dict]:
        """查看消息（不移除）."""
        return _trade_bus.peek(channel, limit)

    @staticmethod
    def subscribe(channel: str, callback: Callable) -> None:
        """订阅频道，有新消息时回调."""
        _subscribers.setdefault(channel, []).append(callback)

    @staticmethod
    def clear() -> None:
        """清空所有频道和订阅."""
        _subscribers.clear()
        for ch in _trade_bus.list_channels():
            _trade_bus.clear_channel(ch)

    @staticmethod
    def list_channels() -> list[str]:
        """列出有消息的活跃频道."""
        return _trade_bus.list_channels()

    # ── 领域专用方法 ──

    @staticmethod
    def signal_researcher_to_risk(signal: dict) -> str:
        """研究员发布交易信号."""
        return _trade_bus.researcher_publish_signal(signal)

    @staticmethod
    def signal_risk_to_trader(decision: dict) -> str:
        """风控官发布审批结果."""
        return _trade_bus.risk_officer_publish_decision(decision)

    @staticmethod
    def signal_trader_result(result: dict) -> str:
        """交易员发布执行结果."""
        return _trade_bus.trader_publish_result(result)

    @staticmethod
    def signal_portfolio_plan(plan: dict) -> str:
        """操盘手发布仓位计划."""
        return _trade_bus.pm_publish_plan(plan)

    @staticmethod
    def send_alert(message: str, level: str = "INFO") -> str:
        """发送告警."""
        return _trade_bus.send_alert(message, level)
