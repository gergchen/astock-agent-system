"""Strategist Agent — 策略师.

职责:
- 每日收盘后全貌复盘
- 次日操作策略生成
- 中线组合调仓建议

触发条件: 收盘后自动触发 / 用户指令
输出: 复盘报告 + 明日早报
"""

import json
import logging
from datetime import datetime

from ..base import BaseAgent, AgentResult
from ...skills.market_skills import MarketSkills
from ...skills.news_skills import NewsSkills
from ...skills.research_skills import ResearchSkills
from ...memory.memory_store import MemoryStore

logger = logging.getLogger(__name__)

STRATEGIST_PROMPT = """你是一名经验丰富的 A 股策略师，曾管理百亿级私募组合。

## 你的能力
- 盘面复盘：指数、量能、板块轮动、情绪周期
- 信号解读：强势股榜单变化、题材热度切换、北向资金动向
- 策略生成：明日操作方向、仓位建议、关键观察标的
- 风险评估：宏观风险、政策风险、外围市场影响

## 输出格式

### 一、盘面回顾
- 主要指数表现（涨跌幅/成交量）
- 涨停/跌停家数
- 热点题材 TOP5 及资金流向

### 二、强势股扫描
- 当日最强方向及代表性个股
- 题材轮动信号（新老题材切换）

### 三、北向资金
- 当日净流向及节奏
- 主要买入/卖出方向

### 四、明日策略
- 操作方向（进攻/防守/观望）
- 仓位建议（轻仓/半仓/重仓）
- 重点关注板块及个股（3-5 只）

### 五、风险提示
- 隔夜需关注的外部事件
- 技术面关键支撑/压力位

## 注意事项
- 基于数据说话，不凭空预测
- 策略要具体可执行，避免模糊建议"""


class Strategist(BaseAgent):
    """策略师 Agent — 复盘 + 明日策略."""

    def __init__(self):
        self.market_api = MarketSkills()
        self.news_api = NewsSkills()
        self.research_api = ResearchSkills()
        self.memory = MemoryStore.get_instance()
        super().__init__(name="strategist", role="策略师")

    def system_prompt(self) -> str:
        return STRATEGIST_PROMPT

    def _register_skills(self) -> None:
        self._skills["get_hotspots"] = self.market_api.get_hotspots
        self._skills["get_sector_hotspots"] = self.market_api.get_sector_hotspots
        self._skills["get_northbound"] = self.market_api.get_northbound
        self._skills["get_flash_news"] = self.news_api.get_flash_news
        self._skills["get_top_headlines"] = self.news_api.get_top_headlines
        self._skills["get_global_news"] = self.news_api.get_global_news
        self._skills["search_geopolitical_news"] = self.news_api.search_geopolitical_news

    def daily_review(self, session_id: str | None = None) -> AgentResult:
        """收盘复盘：收集当日数据 → LLM 生成策略报告。

        Args:
            session_id: 可选会话 ID
        """
        today = datetime.now().strftime("%Y-%m-%d")

        hotspots = self.market_api.get_hotspots()
        sectors = self.market_api.get_sector_hotspots()
        northbound = self.market_api.get_northbound()
        flash_news = self.news_api.get_flash_news(limit=30)
        headlines = self.news_api.get_top_headlines()
        global_news = self.news_api.get_global_news()

        data_pack = {
            "日期": today,
            "强势股榜单": hotspots,
            "题材热度": sectors,
            "北向资金": northbound,
            "今日快讯": flash_news.get("news", [])[:10],
            "全球头条": headlines.get("headlines", [])[:10],
            "全球资讯": global_news.get("news", [])[:10],
        }

        task = f"请对今日 A 股做全貌复盘并生成明日操作策略：\n\n```json\n{json.dumps(data_pack, ensure_ascii=False, indent=2, default=str)}\n```"

        result = self.run(task=task, session_id=session_id)

        if result.success:
            try:
                self.memory.put(
                    key=f"daily_review:{today}",
                    value=result.output[:500],
                    tier="project",
                    tags=["daily_review", "strategy", today],
                )
            except Exception:
                pass

        return result

    def morning_briefing(self, session_id: str | None = None) -> AgentResult:
        """生成早盘简报（基于最近一次复盘 + 隔夜新闻）。

        Args:
            session_id: 可选会话 ID
        """
        today = datetime.now().strftime("%Y-%m-%d")

        flash_news = self.news_api.get_flash_news(limit=20)
        headlines = self.news_api.get_top_headlines()
        global_news = self.news_api.get_global_news()
        northbound = self.market_api.get_northbound()

        # 尝试加载昨日复盘
        yesterday_review = self.memory.search("daily_review", tier="project")

        data_pack = {
            "日期": today,
            "昨日复盘": yesterday_review[0]["value"][:300] if yesterday_review else "无",
            "今日快讯": flash_news.get("news", [])[:10],
            "全球头条": headlines.get("headlines", [])[:10],
            "全球资讯": global_news.get("news", [])[:10],
            "北向资金": northbound,
        }

        task = f"请生成今日早盘操作简报：\n\n```json\n{json.dumps(data_pack, ensure_ascii=False, indent=2, default=str)}\n```"

        return self.run(task=task, session_id=session_id)
