---
name: risk-assessor
description: A股风控评估 — 预交易风险检查（仓位/回撤/连续亏损/ST禁买）
origin: custom
version: 0.1
---

# 风控评估 Skill

对所有交易信号执行风控检查，将结果发布给交易员。

## When to Activate

- 收到研究员信号后自动触发
- 交易员执行前验证
- 用户问"这只票能买吗"
- 关键词：风控、仓位、回撤、止损

## Python Module

```python
from astock_trade.skills.risk_assessor import pre_trade_check, publish_decision

# 执行风控检查
account = {
    "total_assets": 1000000,
    "cash": 500000,
    "positions": {"600519": 100000},
    "daily_pnl": -5000,
}
decision = pre_trade_check(signal, account)
# Returns: {decision: APPROVED|REJECTED, checks: {...}, reason: "..."}

# 发布决策
publish_decision(decision)
```

## 风控规则

| 规则 | 阈值 | 类型 |
|------|------|------|
| 单票仓位 | ≤ 20% | 硬性 |
| 总仓位 | ≤ 70% | 硬性 |
| 日内回撤 | ≤ 5% | 硬性 |
| 连续亏损 | < 3 笔 | 硬性 |
| ST 禁买 | 禁止 | 硬性 |

## 决策格式

```json
{
  "type": "risk_decision",
  "decision": "APPROVED",
  "checks": {"single_stock_position": true, ...},
  "reason": "所有风控检查通过"
}
```
