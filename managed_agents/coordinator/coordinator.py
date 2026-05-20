"""Coordinator — 多 Agent 编排核心.

预定义工作流流水线:
- morning_briefing: 哨兵扫描 → 策略师早报
- intraday_alert: 哨兵异动 → 研究员快析 → 通知
- daily_review: 策略师全貌复盘 → Memory
- stock_deep_dive: 研究员 → 风控官 → 交易员 → 汇总
"""

import logging
from dataclasses import dataclass, field
from typing import Callable

from ..agents.base import AgentResult
from ..memory.memory_store import MemoryStore

logger = logging.getLogger(__name__)


@dataclass
class WorkflowStep:
    agent_name: str
    description: str
    input_from: str | None = None  # 上一个 step 的 id，None = 使用原始输入


@dataclass
class Workflow:
    name: str
    description: str
    steps: list[WorkflowStep] = field(default_factory=list)


class Coordinator:
    """多 Agent 编排器（单例）."""

    _instance: "Coordinator | None" = None

    def __init__(self):
        self._agents: dict[str, object] = {}
        self._workflows: dict[str, Workflow] = {}
        self._memory = MemoryStore.get_instance()
        self._register_workflows()

    @classmethod
    def get_instance(cls) -> "Coordinator":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def register_agent(self, agent):
        self._agents[agent.name] = agent

    def get_agent(self, name: str):
        return self._agents.get(name)

    @property
    def agents(self) -> dict:
        return self._agents

    def _register_workflows(self):
        self._workflows["morning_briefing"] = Workflow(
            name="morning_briefing",
            description="早盘简报：哨兵扫描 → 策略师早报",
            steps=[
                WorkflowStep("sentinel", "哨兵扫描市场"),
                WorkflowStep("strategist", "策略师生早报"),
            ],
        )
        self._workflows["intraday_alert"] = Workflow(
            name="intraday_alert",
            description="盘中异动：哨兵扫描 → 异动检测 → 研究员分析",
            steps=[
                WorkflowStep("sentinel", "哨兵检测异动"),
                WorkflowStep("researcher", "研究员快速分析", input_from="sentinel"),
            ],
        )
        self._workflows["daily_review"] = Workflow(
            name="daily_review",
            description="每日复盘：策略师全貌复盘",
            steps=[
                WorkflowStep("strategist", "策略师复盘"),
            ],
        )
        self._workflows["stock_deep_dive"] = Workflow(
            name="stock_deep_dive",
            description="个股深研：研究员 → 风控官 → 交易员",
            steps=[
                WorkflowStep("researcher", "研究员基本面分析"),
                WorkflowStep("risk_mgr", "风控官风险评估", input_from="researcher"),
                WorkflowStep("trader", "交易员仓位建议", input_from="risk_mgr"),
            ],
        )

    def run(self, workflow_name: str, input_data: str = "",
            session_id: str | None = None) -> dict:
        """执行一个预定义工作流。

        Args:
            workflow_name: 工作流名称
            input_data: 初始输入（如股票代码）
            session_id: 可选会话 ID

        Returns:
            {workflow, steps: [{agent, success, output[:300], elapsed_ms}], final_context}
        """
        wf = self._workflows.get(workflow_name)
        if wf is None:
            raise KeyError(f"Workflow '{workflow_name}' 不存在。可用: {list(self._workflows)}")

        results = []
        context = {"input": input_data}

        for i, step in enumerate(wf.steps):
            agent = self._agents.get(step.agent_name)
            if agent is None:
                results.append({
                    "agent": step.agent_name,
                    "success": False,
                    "output": f"Agent '{step.agent_name}' 未注册",
                })
                continue

            task = self._build_task(step, wf.name, input_data, context, results)
            logger.info(f"[{wf.name}] Step {i+1}/{len(wf.steps)}: {step.agent_name} — {step.description}")

            # 调用 Agent 的核心方法
            result = self._dispatch(agent, step.agent_name, task, wf.name, session_id)

            step_result = {
                "agent": step.agent_name,
                "description": step.description,
                "success": result.success,
                "output": result.output[:500] if result.output else "",
                "elapsed_ms": result.elapsed_ms,
                "error": result.error,
            }
            results.append(step_result)

            # 更新上下文
            context[step.agent_name] = result.output

            if not result.success:
                break

        return {
            "workflow": wf.name,
            "steps": results,
            "final_context": context,
        }

    def _build_task(self, step: WorkflowStep, workflow_name: str,
                    input_data: str, context: dict, prev_results: list[dict]) -> str:
        """构建当前步骤的任务描述."""
        agent = self._agents.get(step.agent_name)

        if step.agent_name == "sentinel":
            return "请扫描当前市场，检测异动并返回分析结果"
        elif step.agent_name == "researcher":
            code = input_data.strip()
            if code and not code.startswith("请"):
                return f"请对股票 {code} 做全方位基本面分析"
            # 否则使用上一步的上下文
            prev_output = context.get("sentinel", "")
            if prev_output:
                return f"基于哨兵扫描结果，请分析其中提到的异动个股：\n{prev_output[:1000]}"
            return input_data or "请分析当前市场热点"
        elif step.agent_name == "risk_mgr":
            code = input_data.strip()
            prev_output = context.get("researcher", "")
            if code and not code.startswith("请"):
                return f"请评估 {code} 的交易风险。研究员分析结论：\n{prev_output[:800]}"
            return f"请评估以下研究结论中涉及股票的交易风险：\n{prev_output[:1000]}"
        elif step.agent_name == "trader":
            code = input_data.strip()
            prev_research = context.get("researcher", "")
            prev_risk = context.get("risk_mgr", "")
            if code and not code.startswith("请"):
                return f"请评估 {code} 的交易信号并给出仓位建议。\n研究员分析：\n{prev_research[:500]}\n风控评估：\n{prev_risk[:500]}"
            return f"请基于以下分析评估交易信号：\n研究员：\n{prev_research[:500]}\n风控：\n{prev_risk[:500]}"
        elif step.agent_name == "strategist":
            if "morning" in workflow_name:
                return "请生成今日早盘操作简报"
            return "请对今日 A 股做全貌复盘并生成明日操作策略"
        else:
            return input_data

    def _dispatch(self, agent, agent_name: str, task: str,
                  workflow_name: str, session_id: str | None) -> AgentResult:
        """根据 Agent 类型调用对应的核心方法."""
        if agent_name == "researcher":
            # 尝试从 task 提取股票代码
            code = self._extract_code(task)
            if code:
                return agent.analyze(code, session_id=session_id)
        elif agent_name == "strategist":
            if "morning" in workflow_name:
                return agent.morning_briefing(session_id=session_id)
            return agent.daily_review(session_id=session_id)
        elif agent_name == "trader":
            code = self._extract_code(task)
            return agent.evaluate_signal(code, signal_info={"task": task}, session_id=session_id)
        elif agent_name == "risk_mgr":
            code = self._extract_code(task)
            return agent.assess_risk(code, session_id=session_id)
        elif agent_name == "sentinel":
            scan_result = agent.scan()
            output = str(scan_result)
            return AgentResult(
                agent_name="sentinel", task_id="coord",
                success=True, output=output, data=scan_result,
            )

        return agent.run(task=task, session_id=session_id)

    def _extract_code(self, text: str) -> str | None:
        """从文本中提取 6 位股票代码."""
        import re
        match = re.search(r'\b(\d{6})\b', text)
        return match.group(1) if match else None
