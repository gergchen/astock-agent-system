"""协调器 — 多 Agent 工作流编排.

4 阶段工作流:
1. Research  — 并行启动研究员 + 分析师 → 收集市场数据
2. Synthesis — 操盘手汇总分析 → 制定方向
3. Execute   — 串行：研究员信号 → 风控审批 → 交易员执行
4. Verify    — 操盘手复盘 + 风控官评估
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed

from .bus import EventBus
from ..agents.base import BaseAgent, AgentResult
from ..agents.registry import AgentRegistry

logger = logging.getLogger(__name__)


@dataclass
class WorkflowResult:
    phase: str
    agent_name: str
    success: bool
    result: dict = field(default_factory=dict)
    elapsed_ms: int = 0
    error: str = ""


class Coordinator:
    """多 Agent 工作流协调器."""

    def __init__(self, max_workers: int = 4):
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._bus = EventBus()
        self._registry = AgentRegistry.get_instance()

    def research_phase(self) -> list[WorkflowResult]:
        """Research 阶段: 并行执行 MorningAnalyst + ResearcherTrader."""
        tasks = {}
        results = []

        agents_to_run = ["morning-analyst", "researcher-trader"]
        futures = {}

        for name in agents_to_run:
            try:
                agent = self._registry.get(name)
                if name == "morning-analyst":
                    future = self._executor.submit(agent.generate_briefing)
                else:
                    future = self._executor.submit(agent.scan_and_generate)
                futures[future] = name
            except KeyError:
                logger.warning(f"Agent '{name}' 未注册，跳过 Research 阶段")
                continue

        for future in as_completed(futures):
            name = futures[future]
            try:
                result = future.result(timeout=60)
                results.append(WorkflowResult(
                    phase="research", agent_name=name,
                    success=True, result=result,
                ))
            except Exception as e:
                logger.error(f"Research phase [{name}] failed: {e}")
                results.append(WorkflowResult(
                    phase="research", agent_name=name,
                    success=False, error=str(e),
                ))

        return results

    def execute_phase(self) -> list[WorkflowResult]:
        """Execute 阶段: 研究员信号 → 风控审批 → 交易员执行."""
        results = []

        try:
            researcher = self._registry.get("researcher-trader")
        except KeyError:
            return [WorkflowResult(phase="execute", agent_name="researcher-trader",
                                   success=False, error="未注册")]

        scan_result = researcher.scan_and_generate()
        results.append(WorkflowResult(
            phase="execute", agent_name="researcher-trader",
            success=True, result=scan_result,
        ))

        # 如果有信号，启动风控+交易链
        if not scan_result.get("signals"):
            return results

        try:
            risk_officer = self._registry.get("risk-officer")
        except KeyError:
            return results

        risk_results = risk_officer.review_pending()
        approved = [r for r in risk_results if r.get("decision") == "APPROVED"]
        results.append(WorkflowResult(
            phase="execute", agent_name="risk-officer",
            success=True, result={"reviewed": len(risk_results), "approved": len(approved)},
        ))

        if not approved:
            return results

        try:
            trader = self._registry.get("day-trader")
        except KeyError:
            return results

        trade_results = trader.execute_pending()
        results.append(WorkflowResult(
            phase="execute", agent_name="day-trader",
            success=True, result={"executed": len(trade_results)},
        ))

        return results

    def verify_phase(self) -> list[WorkflowResult]:
        """Verify 阶段: 操盘手复盘."""
        results = []

        try:
            pm = self._registry.get("portfolio-manager")
        except KeyError:
            return [WorkflowResult(phase="verify", agent_name="portfolio-manager",
                                   success=False, error="未注册")]

        recap = pm.post_market_recap()
        results.append(WorkflowResult(
            phase="verify", agent_name="portfolio-manager",
            success=recap.get("success", True),
            result=recap,
            elapsed_ms=recap.get("elapsed_ms", 0),
        ))

        return results

    def run_full_cycle(self) -> list[WorkflowResult]:
        """运行完整交易周期: Research → Execute → Verify."""
        all_results = []

        logger.info("=== Research Phase ===")
        all_results.extend(self.research_phase())

        logger.info("=== Execute Phase ===")
        all_results.extend(self.execute_phase())

        logger.info("=== Verify Phase ===")
        all_results.extend(self.verify_phase())

        return all_results

    def shutdown(self):
        self._executor.shutdown(wait=True)
