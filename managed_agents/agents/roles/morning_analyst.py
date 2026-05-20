"""盘前分析师 — 晨报生成、隔夜扫描、早盘预判."""

import json
import logging
from pathlib import Path

from ..base import BaseAgent
from ..loader import load_agent_definition

logger = logging.getLogger(__name__)

MORNING_ANALYST_PROMPT = """你是A股晨报分析师，负责每个交易日盘前生成简洁的市场简报。

## 核心职责
1. 隔夜扫描：外围市场、政策消息、公司公告
2. 今日事件：财经日历、政策发布
3. 热点预判：基于消息面预判今日可能活跃的板块
4. 发布晨报：在09:15前输出结构化简报

## 晨报模板
```
# A股盘前简报 — YYYY-MM-DD

## 外围市场
- 美股/A50/港股期货

## 重磅消息
- 逐条列出

## 今日关注
- 题材方向 + 活跃板块 + 回避板块

## 北向资金
- 昨日流向

## 风险提示
```

## 注意事项
- 晨报必须简洁，5分钟内可读完
- 不提供买卖建议，只做信息汇总
- 重点关注机构动向和政策面消息
"""


class MorningAnalyst(BaseAgent):
    """盘前分析师 Agent."""

    def __init__(self):
        from astock_trade.skills.morning_scan import premarket_scan, latest_flash_news
        from astock_trade.skills.postmarket_recap import daily_recap

        self._premarket_scan = premarket_scan
        self._latest_flash_news = latest_flash_news
        self._daily_recap = daily_recap

        super().__init__(name="morning-analyst", role="盘前分析师")

    def system_prompt(self) -> str:
        return MORNING_ANALYST_PROMPT

    def _register_skills(self):
        self._skills.update({
            "premarket_scan": lambda: self._premarket_scan(),
            "latest_flash_news": lambda n=20: self._latest_flash_news(n),
            "daily_recap": lambda d=None: self._daily_recap(d),
        })

    def generate_briefing(self) -> dict:
        """生成盘前简报."""
        try:
            data = self._premarket_scan()
        except Exception as e:
            logger.error(f"盘前数据获取失败: {e}")
            return {"error": str(e)}

        task = f"请基于以下数据生成今日盘前简报:\n{json.dumps(data, ensure_ascii=False, indent=2)}"
        result = self.run(task=task)
        return {
            "success": result.success,
            "briefing": result.output,
            "data": data,
            "elapsed_ms": result.elapsed_ms,
        }
