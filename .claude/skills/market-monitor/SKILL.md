---
name: market-monitor
description: A股盘中实时监控 — 热点板块轮动、北向资金异动、个股行情追踪
origin: custom
version: 0.1
---

# 盘中监控 Skill

交易时段（09:30-15:00）实时扫描，用于研究员和交易员监控市场。

## When to Activate

- 用户要求盘中分析 / 看盘 / 行情
- 用户问"现在什么板块强"
- 用户问"北向资金怎么样"
- 自动调度触发 market_monitor 任务
- 关键词：盘中、资金动向、热点、板块、北向、沪股通、深股通

## CLI Commands

```bash
# 当前热点板块
python -m astock_data.cli signal hotspot --sectors

# 北向资金分钟级
python -m astock_data.cli signal northbound

# 个股行情
python -m astock_data.cli market quote <code>

# 个股K线
python -m astock_data.cli market kline <code> -c 5m -n 50
```

## Python Module

```python
from astock_trade.skills.market_monitor import scan_now, scan_hotspots

data = scan_now()
# Returns: {timestamp, hotspots, northbound_latest}
```

## 告警触发

- 北向单分钟净流入/流出超5亿 → 通知用户
- 板块排名剧烈变动（上升/下降 > 3位）→ 通知用户
