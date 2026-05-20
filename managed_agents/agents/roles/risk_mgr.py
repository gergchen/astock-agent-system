"""RiskMgr Agent — 风控官.

职责:
- 持仓敞口监控
- 单票/组合风险度量
- 止损检查 & 合规校验
- 黑名单过滤

触发条件: 每笔交易前自动触发
输出: 通过/否决 + 风险评估报告
"""

import json
import logging

from ..base import BaseAgent, AgentResult
from ...skills.market_skills import MarketSkills
from ...skills.fundamental_skills import FundamentalSkills
from ...skills.news_skills import NewsSkills

logger = logging.getLogger(__name__)

RISK_MGR_PROMPT = """你是一名严格的风控官，负责把控投资组合的每一笔风险。

## 风控规则
- 单票仓位上限：20%
- 单一行业上限：40%
- 总仓位上限：80%（永远保留 20% 现金）
- ST/退市整理/*ST 股票一律否决
- 跌停板股票禁止买入
- 新股上市 30 天内不可重仓（≤5%）
- 重大负面公告（立案调查/ST 预警）一票否决

## 输出格式

### 风险评估
- 风险等级：低/中/高/极高
- 主要风险点

### 风控决定
- 通过 / 有条件通过 / 否决
- 条件说明（如适用）

### 风险参数
- 建议单票上限（按波动率调整）
- 止损触发价
- 组合影响评估

## 注意事项
- 宁可错杀不可放过
- 怀疑即否决
- 重大不确定性 = 否决"""


class RiskMgr(BaseAgent):
    """风控官 Agent — 敞口监控 + 止损检查."""

    def __init__(self):
        self.market_api = MarketSkills()
        self.fund_api = FundamentalSkills()
        self.news_api = NewsSkills()
        super().__init__(name="risk_mgr", role="风控官")

    def system_prompt(self) -> str:
        return RISK_MGR_PROMPT

    def _register_skills(self) -> None:
        self._skills["get_quote"] = self.market_api.get_quote
        self._skills["get_stock_basics"] = self.fund_api.get_stock_basics
        self._skills["get_finance"] = self.fund_api.get_finance
        self._skills["get_stock_news"] = self.news_api.get_stock_news
        self._skills["get_announcements"] = self.fund_api.get_f10

    def assess_risk(self, code: str, position: dict | None = None,
                    portfolio: dict | None = None,
                    session_id: str | None = None) -> AgentResult:
        """评估单只股票的交易风险。

        Args:
            code: 股票代码
            position: 计划持仓信息 {ratio, cost, stop_loss, ...}
            portfolio: 当前组合概况 {total_asset, positions, ...}
            session_id: 可选会话 ID
        """
        def _safe_fetch(fn, *args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except Exception as e:
                logger.warning(f"RiskMgr data fetch failed: {e}")
                return {}

        basics = _safe_fetch(self.fund_api.get_stock_basics, code)
        finance = _safe_fetch(self.fund_api.get_finance, code)
        news = _safe_fetch(self.news_api.get_stock_news, code)
        quote = _safe_fetch(self.market_api.get_quote, [code])

        data_pack = {
            "代码": code,
            "基本信息": basics.get("basics", {}),
            "财务快照": finance.get("finance", {}),
            "实时行情": quote.get("quotes", []),
            "近期新闻": news.get("news", [])[:10],
            "计划持仓": position or {},
            "当前组合": portfolio or {},
        }

        task = f"请评估以下股票的交易风险并做出风控决定：\n\n```json\n{json.dumps(data_pack, ensure_ascii=False, indent=2)}\n```"

        return self.run(task=task, session_id=session_id)
