"""交易员 — 订单执行、仓位追踪、交易日志."""

import json
import logging
from datetime import datetime

from ..base import BaseAgent

logger = logging.getLogger(__name__)

TRADER_PROMPT = """你是A股交易员，负责执行经风控审批的交易指令。你不做交易决策，只做执行。

## 核心职责
1. 接收指令：从消息总线 from_risk_officer 读取批准的交易指令
2. 执行订单：通过 broker 接口下单
3. 记录交易：写入交易日志
4. 追踪持仓：监控持仓盈亏，向风控官汇报

## 执行流程
1. 从消息总线读取审批通过的指令
2. 确认当前持仓和资金允许执行
3. 通过 broker 下单
4. 将执行结果写入交易日志
5. 发布结果到 from_trader channel

## 注意事项
- 仅在风控审批后执行
- 市价单需额外确认（模拟阶段不做市价单）
- 执行失败立刻通知风控官和用户
- 收盘前5分钟停止新开仓
"""


class DayTrader(BaseAgent):
    """交易员 Agent."""

    def __init__(self, broker=None):
        from astock_trade.broker import create_broker, OrderSide
        from astock_trade.bus import trader_consume_decisions, trader_publish_result
        from astock_trade.trade_journal import record_trade

        self._broker = broker if broker is not None else create_broker()
        self._OrderSide = OrderSide
        self._consume_decisions = trader_consume_decisions
        self._publish_result = trader_publish_result
        self._record_trade = record_trade

        super().__init__(name="day-trader", role="交易员")

    def system_prompt(self) -> str:
        return TRADER_PROMPT

    def _register_skills(self):
        self._skills.update({
            "get_account": lambda: self._broker.get_account().__dict__,
            "get_positions": lambda: [p.__dict__ for p in self._broker.get_positions()],
            "consume_decisions": lambda n=1: self._consume_decisions(n),
            "place_order": lambda **kw: self._place_order(**kw),
        })

    def _place_order(self, symbol: str, direction: str, price: float,
                     volume: int, strategy: str | None = None) -> dict:
        """执行下单."""
        side = self._OrderSide.BUY if direction.upper() == "BUY" else self._OrderSide.SELL
        order = self._broker.place_order(symbol, side, price, volume)

        result = {
            "order_id": order.order_id,
            "symbol": order.symbol,
            "direction": order.side.value,
            "price": order.filled_price or order.price,
            "volume": order.filled_volume,
            "strategy": strategy,
            "status": order.status.value,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }

        try:
            self._publish_result(result)
        except Exception as e:
            logger.error(f"发布交易结果失败: {e}")

        try:
            self._record_trade(
                symbol=symbol,
                direction=direction.upper(),
                price=price,
                volume=volume,
                strategy=strategy,
                notes=f"order_id={order.order_id}",
            )
        except Exception as e:
            logger.error(f"记录交易失败: {e}")

        return result

    def execute_pending(self) -> list[dict]:
        """执行所有待处理的已批准交易指令."""
        results = []
        decisions = self._consume_decisions(10)

        for decision in decisions:
            if decision.get("decision") != "APPROVED":
                continue

            signal = decision.get("signal", {})
            try:
                result = self._place_order(
                    symbol=signal["symbol"],
                    direction=signal["direction"],
                    price=signal["price"],
                    volume=decision.get("adjusted_volume", signal.get("volume", 100)),
                    strategy=signal.get("strategy"),
                )
                results.append({"decision": decision, "result": result, "success": True})
            except Exception as e:
                logger.error(f"执行订单失败: {e}")
                results.append({"decision": decision, "error": str(e), "success": False})

        return results
