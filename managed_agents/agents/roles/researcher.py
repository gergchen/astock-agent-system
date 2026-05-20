"""Researcher Agent — 研究员.

职责:
- 研报检索与分析
- 估值建模 (PE/PB/PEG/一致预期)
- 产业链调研
- 个股全方位基本面分析

触发条件: 哨兵异动 / 用户指定股票
输出: 个股研报摘要 + 估值结论 + 评级建议
"""

import json
import logging

from ..base import BaseAgent, AgentResult
from ...skills.research_skills import ResearchSkills
from ...skills.fundamental_skills import FundamentalSkills
from ...skills.news_skills import NewsSkills
from ...skills.announcement_skills import AnnouncementSkills
from ...memory.memory_store import MemoryStore

logger = logging.getLogger(__name__)

RESEARCHER_PROMPT = """你是一名资深 A 股研究员，曾在多家头部券商担任首席分析师。

## 你的能力
- 快速检索和阅读研报，提取关键结论
- 估值建模：PE/PB/PEG/一致预期/估值水位
- 产业链调研：上下游景气度、竞争格局
- 新闻与公告解读：识别信息对股价的影响方向

## 输出格式
分析每只股票时，请按以下结构输出：

### 1. 基本信息
- 行业、市值、流通股本

### 2. 估值分析
- 当前 PE/PB/PEG 及历史分位
- 一致预期 EPS 及增速
- 估值结论：低估/合理/高估

### 3. 研报观点
- 近期研报核心观点摘要
- 多空分歧点

### 4. 近期催化剂
- 最新公告/新闻中的关键信息
- 产业链动态

### 5. 综合评级
- 买入/增持/持有/减持/卖出
- 核心逻辑（一句话）

## 注意事项
- 数据缺失时明确说明，不要编造
- 估值判断结合行业特性（成长股看 PEG，价值股看 PB）"""


class Researcher(BaseAgent):
    """研究员 Agent — 个股全方位基本面分析."""

    def __init__(self):
        self.research_api = ResearchSkills()
        self.fund_api = FundamentalSkills()
        self.news_api = NewsSkills()
        self.ann_api = AnnouncementSkills()
        self.memory = MemoryStore.get_instance()
        super().__init__(name="researcher", role="研究员")

    def system_prompt(self) -> str:
        return RESEARCHER_PROMPT

    def _register_skills(self) -> None:
        self._skills["get_reports"] = self.research_api.get_reports
        self._skills["get_consensus_eps"] = self.research_api.get_consensus_eps
        self._skills["semantic_search"] = self.research_api.semantic_search
        self._skills["full_valuation"] = self.research_api.full_valuation
        self._skills["get_finance"] = self.fund_api.get_finance
        self._skills["get_stock_basics"] = self.fund_api.get_stock_basics
        self._skills["get_stock_news"] = self.news_api.get_stock_news
        self._skills["get_announcements"] = self.ann_api.get_announcements

    def analyze(self, code: str, session_id: str | None = None) -> AgentResult:
        """对单只股票做全方位基本面分析。

        自动收集：估值 + 财务 + 研报 + 新闻 + 公告，
        然后调用 LLM 做综合分析。

        Args:
            code: 股票代码
            session_id: 可选会话 ID
        """
        def _safe_fetch(fn, *args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except Exception as e:
                logger.warning(f"Researcher data fetch failed: {e}")
                return {}

        basics = _safe_fetch(self.fund_api.get_stock_basics, code)
        valuation = _safe_fetch(self.research_api.full_valuation, code)
        eps = _safe_fetch(self.research_api.get_consensus_eps, code)
        reports = _safe_fetch(self.research_api.get_reports, code, max_pages=2)
        news = _safe_fetch(self.news_api.get_stock_news, code)
        announcements = _safe_fetch(self.ann_api.get_announcements, code)

        data_pack = {
            "代码": code,
            "基本信息": basics.get("basics", {}),
            "估值": valuation.get("valuation", {}),
            "一致预期": eps.get("eps_consensus", {}),
            "研报": reports.get("reports", [])[:5],
            "新闻": news.get("news", [])[:5],
            "公告": announcements.get("announcements", [])[:5],
        }

        task = f"请对以下股票做全方位基本面分析：\n\n```json\n{json.dumps(data_pack, ensure_ascii=False, indent=2)}\n```"

        result = self.run(task=task, session_id=session_id)

        # 自动蒸馏到 memory
        if result.success:
            try:
                name = basics.get("basics", {}).get("name", code)
                self.memory.save_session_summary(
                    session_id=session_id or f"analyze_{code}",
                    summary=f"[{name}] {result.output[:300]}",
                    tags=[code, "research", "analysis"],
                )
            except Exception:
                pass

        return result
