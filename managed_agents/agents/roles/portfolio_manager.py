"""操盘手 — 仓位管理、组合优化、多策略协调."""

import json
import logging
from datetime import date, datetime

from ..base import BaseAgent

logger = logging.getLogger(__name__)

PM_PROMPT = """你是A股操盘手（投资组合经理），负责全局仓位管理和策略协调。你不是执行者，而是决策者。

## 核心职责
1. 仓位规划：盘前决定当日仓位和板块配置比例
2. 策略调度：协调多个策略的运行权重
3. 盘中调仓：基于市场变化调整持仓结构
4. 盘后复盘：总结当日交易、盈亏归因、策略表现

## 盘前规划流程 (09:00-09:25)
1. 读取昨日交易汇总和持仓
2. 扫描隔夜消息和外围市场
3. 分析今日热点板块和资金方向
4. 制定今日仓位计划（总仓位目标/行业配置/个股候选池）
5. 写入 portfolio_plan

## 盘后复盘流程 (15:00-16:00)
1. 汇总当日所有交易
2. 计算盈亏和归因
3. 评估各策略表现
4. 生成绩效报告

## 操盘手与研究员协作
- 操盘手设定方向（看多/看空/震荡/观望）
- 研究员在给定方向上发现具体机会
- 操盘手不直接发单，通过研究员→风控→交易员链路

## 注意事项
- 保持全局视角，不被单只股票波动干扰
- 市场重大事件发生时及时调整仓位计划
"""


class PortfolioManager(BaseAgent):
    """操盘手 Agent."""

    def __init__(self):
        from astock_trade.skills.morning_scan import premarket_scan
        from astock_trade.skills.postmarket_recap import daily_recap, today_hotspots, today_northbound_final
        from astock_trade.skills.signal_generator import generate_signals
        from astock_trade.bus import pm_publish_plan
        from astock_trade.strategy_store import list_strategies, load_strategy
        from astock_trade.trade_journal import query_trades, trade_summary

        self._premarket_scan = premarket_scan
        self._daily_recap = daily_recap
        self._today_hotspots = today_hotspots
        self._today_northbound_final = today_northbound_final
        self._generate_signals = generate_signals
        self._pm_publish_plan = pm_publish_plan
        self._list_strategies = list_strategies
        self._load_strategy = load_strategy
        self._query_trades = query_trades
        self._trade_summary = trade_summary

        super().__init__(name="portfolio-manager", role="操盘手")

    def system_prompt(self) -> str:
        return PM_PROMPT

    def _register_skills(self):
        self._skills.update({
            "premarket_scan": lambda: self._premarket_scan(),
            "daily_recap": lambda d=None: self._daily_recap(d),
            "today_hotspots": lambda: self._today_hotspots(),
            "today_northbound": lambda: self._today_northbound_final(),
            "list_strategies": lambda: self._list_strategies(),
            "query_trades": lambda start, end: self._query_trades(start, end),
            "trade_summary": lambda start, end: self._trade_summary(start, end),
        })

    def pre_market_plan(self) -> dict:
        """生成盘前仓位计划."""
        try:
            data = self._premarket_scan()
        except Exception as e:
            logger.error(f"盘前扫描失败: {e}")
            return {"error": str(e)}

        strategies = self._list_strategies()
        task = (
            f"请基于以下数据制定今日仓位计划:\n"
            f"市场数据:\n{json.dumps(data, ensure_ascii=False, indent=2)}\n\n"
            f"可用策略: {json.dumps(strategies, ensure_ascii=False)}\n\n"
            f"输出格式: 总仓位目标(0-70%), 行业配置, 候选池, 方向判断"
        )

        result = self.run(task=task)

        plan = {
            "date": date.today().isoformat(),
            "direction": "观望",
            "total_position_target": 0,
            "sector_allocation": {},
            "watchlist": [],
            "briefing": result.output if result.success else "",
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }

        try:
            self._pm_publish_plan(plan)
        except Exception as e:
            logger.error(f"发布仓位计划失败: {e}")

        return {"success": result.success, "plan": plan, "elapsed_ms": result.elapsed_ms}

    def post_market_recap(self) -> dict:
        """执行盘后复盘（含模式学习）。"""
        try:
            recap = self._daily_recap()
        except Exception as e:
            logger.error(f"盘后复盘失败: {e}")
            return {"error": str(e)}

        # ── 运行模式学习 ──
        try:
            from managed_agents.experience.pattern_learner import run_pattern_analysis
            from datetime import timedelta
            patterns = run_pattern_analysis(
                start_date=date.today() - timedelta(days=60),
                end_date=date.today(),
            )
            logger.info(f"模式学习完成: {patterns.get('total_roundtrips', 0)} 笔已平仓交易")
        except Exception as e:
            logger.warning(f"模式学习跳过: {e}")
            patterns = {"status": "skipped"}

        task = (
            f"请基于以下数据做盘后复盘，总结当日交易、盈亏归因、策略评估:\n"
            f"{json.dumps(recap, ensure_ascii=False, indent=2)}\n\n"
            f"近期历史模式参考:\n{json.dumps(patterns, ensure_ascii=False, indent=2)}"
        )

        result = self.run(task=task)
        return {
            "success": result.success,
            "recap": result.output,
            "data": recap,
            "patterns": patterns,
            "elapsed_ms": result.elapsed_ms,
        }
