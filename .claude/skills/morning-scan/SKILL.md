---
name: morning-scan
description: A股盘前扫描 — 隔夜消息、外围市场、热点板块、北向资金。用于生成盘前简报。
origin: custom
version: 0.1
---

# 盘前扫描 Skill

盘前（09:00-09:25）全维度扫描，为晨报分析师提供结构化数据。

## When to Activate

- 用户要求盘前分析 / 盘前简报 / 盘前扫描
- 用户问"今天有什么关注"
- 自动调度触发 morning_scan 任务
- 关键词：盘前、早盘、晨报、隔夜、开盘前

## CLI Commands

```bash
# 昨日热点板块排名
python -m astock_data.cli signal hotspot --sectors

# 最新快讯（隔夜+今早）
python -m astock_data.cli news flash -n 20

# 北向资金昨日汇总
python -m astock_data.cli signal northbound
```

## Python Module

```python
from astock_trade.skills.morning_scan import premarket_scan

data = premarket_scan()
# Returns: {date, hotspots, news, northbound}
```

## 输出模板

```markdown
# 盘前简报 — {date}

## 外围市场
- 美股/港股/A50期货

## 重磅消息
- Top 5 快讯

## 今日关注
- 热点板块 Top 5
- 北向资金动向

## 风险提示
```
