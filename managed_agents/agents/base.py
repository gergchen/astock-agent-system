"""BaseAgent — 所有 Agent 的抽象基类.

Every Agent has:
- Identity: name, role, system_prompt
- Capabilities: tools/skills it can call
- Lifecycle: init -> run -> shutdown
"""

import time
import uuid
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable

from ..config import get_config
from ..api.client import get_client

logger = logging.getLogger(__name__)


@dataclass
class AgentResult:
    """Agent 执行结果."""
    agent_name: str
    task_id: str
    success: bool
    output: str
    data: dict = field(default_factory=dict)
    elapsed_ms: int = 0
    error: str = ""


class BaseAgent(ABC):
    """所有 Agent 的抽象基类.

    子类只需实现 system_prompt() 和 _register_skills() 两个方法.
    """

    def __init__(self, name: str, role: str):
        self.name = name
        self.role = role
        self.config = get_config()
        self._skills: dict[str, Callable] = {}
        self._register_skills()

    @abstractmethod
    def system_prompt(self) -> str:
        """返回该 Agent 的系统提示词."""
        ...

    @abstractmethod
    def _register_skills(self) -> None:
        """子类在此注册技能: self._skills['name'] = func."""
        ...

    def _call_llm(self, messages: list[dict]) -> str:
        """调用 LLM API (通过统一客户端)."""
        return get_client().call(messages)

    def run(self, task: str, context: dict | None = None,
            session_id: str | None = None) -> AgentResult:
        """执行一个任务，可选关联 session 进行转录记录.

        Args:
            task: 任务描述
            context: 额外上下文
            session_id: 关联的会话 ID (用于转录恢复)
        """
        task_id = uuid.uuid4().hex[:12]
        start = time.time()

        # 延迟导入避免循环依赖
        from ..sessions.transcript import TranscriptWriter, TranscriptEvent
        from ..sessions.compaction import Compactor, estimate_tokens
        from ..utils.token_optimizer import compress as optimize_payload

        transcript = TranscriptWriter(session_id) if session_id else None
        compactor = Compactor()

        try:
            messages = []
            if context:
                ctx_str = json.dumps(context, ensure_ascii=False, indent=2, default=str)
                messages.append({
                    "role": "user",
                    "content": f"背景:\n{ctx_str}",
                })

            # Token 优化：压缩 JSON payload
            optimized_task = self._optimize_task(task, optimize_payload)

            full_task = f"{self._build_system()}\n\n---\n\n任务: {optimized_task}"
            messages.append({"role": "user", "content": full_task})

            if transcript:
                transcript.append(TranscriptEvent(role="user", content=full_task))

            # 自动压缩 (token ≥ 100K)
            if estimate_tokens(messages) >= 100000:
                result = compactor.maybe_compact(messages)
                messages = result.messages
                if transcript:
                    transcript.append(TranscriptEvent(
                        role="system",
                        content=f"[AutoCompact: {result.level}]",
                        metadata={"compacted_count": result.compacted_count},
                    ))

            output = self._call_llm(messages)
            elapsed = int((time.time() - start) * 1000)

            if transcript:
                transcript.append(TranscriptEvent(role="assistant", content=output))
                transcript.close()

            return AgentResult(
                agent_name=self.name, task_id=task_id,
                success=True, output=output, elapsed_ms=elapsed,
            )
        except Exception as e:
            logger.error(f"[{self.name}] task failed: {e}")
            if transcript:
                transcript.append(TranscriptEvent(
                    role="system", content=f"Error: {e}",
                    metadata={"error": str(e)},
                ))
                transcript.close()
            return AgentResult(
                agent_name=self.name, task_id=task_id,
                success=False, output="", error=str(e),
                elapsed_ms=int((time.time() - start) * 1000),
            )

    def call_skill(self, name: str, **kwargs):
        """调用已注册的技能."""
        if name not in self._skills:
            raise ValueError(f"Skill '{name}' 未注册. 可用: {list(self._skills)}")
        return self._skills[name](**kwargs)

    def _build_system(self) -> str:
        sp = self.system_prompt()
        if self._skills:
            sp += "\n\n## 可用工具\n"
            for sn, fn in self._skills.items():
                doc = (fn.__doc__ or "").strip().split("\n")[0]
                sp += f"- {sn}: {doc}\n"
        return sp

    def _optimize_task(self, task: str, optimize_payload) -> str:
        """RTK 风格 Token 压缩：自动检测并压缩任务中的 JSON payload."""
        import re
        try:
            def _compress_json_block(match):
                json_str = match.group(1)
                try:
                    data = json.loads(json_str)
                    compressed = optimize_payload(data)
                    return "\n```json\n" + json.dumps(compressed, ensure_ascii=False, indent=2, default=str) + "\n```"
                except (json.JSONDecodeError, TypeError):
                    return match.group(0)

            # 压缩 markdown json 代码块
            task = re.sub(r'```json\n(.*?)\n```', _compress_json_block, task, flags=re.DOTALL)

            # 压缩内联 JSON（无代码块包装的纯 JSON）
            # 仅在 task 开头就是 { 时处理
            task_stripped = task.strip()
            if task_stripped.startswith("{") and "```" not in task_stripped:
                try:
                    data = json.loads(task_stripped)
                    compressed = optimize_payload(data)
                    return json.dumps(compressed, ensure_ascii=False, indent=2, default=str)
                except (json.JSONDecodeError, TypeError):
                    pass
        except Exception as e:
            logger.debug(f"Token optimization skipped: {e}")

        return task
