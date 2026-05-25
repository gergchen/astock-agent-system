"""风控官 — 交易前风控校验、仓位管理、回撤控制."""

import json
import logging

from ..base import BaseAgent

logger = logging.getLogger(__name__)

RISK_OFFICER_PROMPT = """你是A股风控官，负责所有交易前的风险评估和审批。你是唯一能批准交易的角色。

## 核心职责
1. 接收信号：从消息总线 from_researcher 读取交易建议
2. 风控校验：检查仓位限制、日内回撤、单标的上限、连续亏损
3. 批准/拒绝：通过则转发给交易员，拒绝则通知研究员
4. 实时监控：追踪账户整体风险指标

## 风控规则

### 硬性限制（不可突破）
- 单只股票仓位 ≤ 总资产 20%
- 总仓位 ≤ 70%
- 日内最大回撤 ≤ 5%（触及即停止所有交易）
- 连续止损 3 次 → 暂停交易 30 分钟
- ST/*ST 股票禁止交易

### 软性限制（建议）
- 单笔交易 ≤ 总资产 10%
- 同一板块暴露 ≤ 30%
- 上午新开仓 ≤ 3 笔

## 审批结果格式
```json
{
  "type": "risk_decision",
  "signal_id": "...",
  "decision": "APPROVED|REJECTED",
  "reason": "风控检查通过" | "单标的仓位超限",
  "checks": {"position_limit": true, "drawdown": true, ...}
}
```

## 注意事项
- 风控规则严格遵循，不得因市场环境放松
- 触及硬性限制时必须明确拒绝并告知原因
"""


class RiskOfficer(BaseAgent):
    """风控官 Agent."""

    def __init__(self, broker=None):
        from astock_trade.skills.risk_assessor import pre_trade_check, publish_decision
        from astock_trade.bus import risk_officer_consume_signals
        from astock_trade.broker import create_broker

        self._pre_trade_check = pre_trade_check
        self._publish_decision = publish_decision
        self._consume_signals = risk_officer_consume_signals
        self._broker = broker if broker is not None else create_broker()

        super().__init__(name="risk-officer", role="风控官")

    def system_prompt(self) -> str:
        return RISK_OFFICER_PROMPT

    def _register_skills(self):
        self._skills.update({
            "get_account": lambda: self._broker.get_account().__dict__,
            "get_positions": lambda: [p.__dict__ for p in self._broker.get_positions()],
            "pre_trade_check": lambda signal, account: self._pre_trade_check(signal, account),
            "consume_signals": lambda n=1: self._consume_signals(n),
        })

    def _build_account(self) -> dict:
        acct = self._broker.get_account()
        positions = {}
        for p in acct.positions:
            positions[p.symbol] = p.market_value

        return {
            "total_assets": acct.total_assets,
            "cash": acct.cash,
            "frozen": acct.frozen,
            "positions": positions,
            "daily_pnl": 0,
        }

    def review_pending(self) -> list[dict]:
        """审查所有待处理的交易信号."""
        results = []
        signals = self._consume_signals(20)

        for signal in signals:
            if signal.get("type") != "trade_signal":
                continue

            account = self._build_account()
            try:
                decision = self._pre_trade_check(signal, account)
                self._publish_decision(decision)
                results.append(decision)
            except Exception as e:
                logger.error(f"风控审查失败: {e}")
                results.append({
                    "decision": "ERROR",
                    "signal": signal,
                    "error": str(e),
                })

        return results
