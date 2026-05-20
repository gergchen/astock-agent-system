---
name: signal-generator
description: A股交易信号生成 — 基于热点+北向+K线产生结构化交易建议
origin: custom
version: 0.1
---

# 交易信号生成 Skill

从市场数据生成结构化交易信号，发送给风控官。

## When to Activate

- 研究员 Agent 完成扫描后自动触发
- 用户要求"有什么交易机会"
- 关键词：信号、交易机会、买卖点、入场

## Python Module

```python
from astock_trade.skills.signal_generator import (
    generate_signals, generate_single_signal, publish_signal,
)

# 从扫描数据生成信号
signals = generate_signals(hotspots, northbound)

# 发布到消息总线
for sig in signals:
    publish_signal(sig)
```

## 信号格式

```json
{
  "type": "trade_signal",
  "symbol": "600519",
  "direction": "BUY",
  "price": 1850.00,
  "volume": 100,
  "reason": "放量突破+北向流入+板块联动",
  "strategy": "breakout_v1",
  "confidence": 0.75,
  "timestamp": "..."
}
```

## 信号规则

- 同一标的 30 分钟内不重复发
- 信号必须包含置信度（0-1）
- 信号不直接发给交易员，必须经过风控官
