---
name: postmarket-recap
description: A股盘后复盘 — 盈亏汇总、策略归因、明日展望
origin: custom
version: 0.1
---

# 盘后复盘 Skill

收盘后（15:00-16:00）汇总当日数据，生成复盘报告。

## When to Activate

- 用户要求复盘 / 盘后分析 / 今日总结
- 自动调度触发 postmarket_recap 任务
- 关键词：复盘、盘后、总结、今天怎么样、亏了、赚了

## CLI Commands

```bash
# 今日交易汇总
python -m astock_trade.cli journal summary --start $(date +%Y-%m-%d) --end $(date +%Y-%m-%d)

# 今日 P&L
python -m astock_trade.cli journal pnl -d $(date +%Y-%m-%d)

# 最终热点排名
python -m astock_data.cli signal hotspot --sectors

# 最终北向资金
python -m astock_data.cli signal northbound
```

## Python Module

```python
from astock_trade.skills.postmarket_recap import daily_recap

recap = daily_recap()
# Returns: {date, summary, by_symbol, hotspots, northbound}
```

## 输出模板

```markdown
# 盘后复盘 — {date}

## 盈亏汇总
- 买入 {n} 笔，卖出 {n} 笔
- 净现金流：+X.XX

## 持仓分析
- 按标的汇总盈亏

## 今日热点
- Top 5 板块

## 北向资金
- 最终净流入/流出

## 明日关注
```
