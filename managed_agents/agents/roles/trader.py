"""Trader Agent — 交易员.

职责:
- 交易信号确认（技术面 + 基本面交叉验证）
- 仓位计算（凯利公式 / 风险预算）
- 买卖点建议

触发条件: 研究员推荐 + 风控绿灯
输出: 交易指令（标的/方向/仓位/止损价）
"""

import json
import logging

from ..base import BaseAgent, AgentResult
from ...skills.market_skills import MarketSkills
from ...skills.research_skills import ResearchSkills

logger = logging.getLogger(__name__)

TRADER_PROMPT = """你是一名职业 A 股交易员，有 15 年实盘经验，擅长短线波段交易。

## 你的能力
- 信号确认：技术面 + 基本面 + 资金面三维交叉验证
- 仓位计算：根据风险预算和波动率计算最优仓位
- 买卖点：结合盘口和分时图判断最佳入场/离场时机

## 仓位规则
- 单票最大仓位：总资金 20%
- 首次建仓：目标仓位 50%，确认趋势后加仓
- 止损：-8% 无条件止损
- 止盈：+15% 开始分批止盈

## 输出格式

### 信号评估
- 信号来源 & 强度（1-10）
- 多空因素罗列

### 技术面
- 关键均线位置
- 支撑/压力位
- 量价配合情况

### 仓位建议
- 建议仓位比例
- 分批建仓计划

### 风控参数
- 止损价
- 止盈价
- 最大回撤预期

## 注意事项
- 信号不明确时宁可错过
- 顺势而为，不抄底不逃顶"""


class Trader(BaseAgent):
    """交易员 Agent — 信号确认 + 仓位管理."""

    def __init__(self):
        self.market_api = MarketSkills()
        self.research_api = ResearchSkills()
        super().__init__(name="trader", role="交易员")

    def system_prompt(self) -> str:
        return TRADER_PROMPT

    def _register_skills(self) -> None:
        self._skills["get_quote"] = self.market_api.get_quote
        self._skills["get_hotspots"] = self.market_api.get_hotspots
        self._skills["get_northbound"] = self.market_api.get_northbound
        self._skills["full_valuation"] = self.research_api.full_valuation

    def evaluate_signal(self, code: str, signal_info: dict | None = None,
                        session_id: str | None = None) -> AgentResult:
        """评估交易信号并给出仓位建议。

        Args:
            code: 股票代码
            signal_info: 信号来源信息（如哨兵异动、研究员推荐理由）
            session_id: 可选会话 ID
        """
        def _safe_fetch(fn, *args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except Exception as e:
                logger.warning(f"Trader data fetch failed: {e}")
                return {}

        quote = _safe_fetch(self.market_api.get_quote, [code])
        valuation = _safe_fetch(self.research_api.full_valuation, code)

        data_pack = {
            "代码": code,
            "实时行情": quote.get("quotes", []),
            "估值": valuation.get("valuation", {}),
            "信号来源": signal_info or {},
        }

        task = f"请评估以下交易信号并给出仓位建议：\n\n```json\n{json.dumps(data_pack, ensure_ascii=False, indent=2)}\n```"

        return self.run(task=task, session_id=session_id)
