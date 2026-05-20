"""SessionManager — Agent 会话生命周期管理.

每个 Session 代表一次 Agent 任务执行:
1. 创建 Session (create)
2. 异步执行 (execute, 后台线程)
3. 查询状态 (query)
4. 恢复执行 (resume, 从转录文件恢复上下文)

支持断线续跑: 微信断开后 Agent 继续后台执行,
重新连接后可查询进度和结果.
"""

import logging
import threading
import uuid
from typing import Callable

from .session_store import SessionStore, Session
from .transcript import TranscriptReader
from .compaction import Compactor, estimate_tokens
from ..agents.base import BaseAgent, AgentResult

logger = logging.getLogger(__name__)


class SessionManager:
    """会话管理器 (单例)."""

    _instance: "SessionManager | None" = None

    def __init__(self):
        self._store = SessionStore()
        self._agents: dict[str, BaseAgent] = {}
        self._running: dict[str, threading.Thread] = {}
        self._callbacks: dict[str, list[Callable]] = {}

    @classmethod
    def get_instance(cls) -> "SessionManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def register_agent(self, agent: BaseAgent):
        self._agents[agent.name] = agent

    def on_complete(self, session_id: str, callback: Callable):
        """注册完成回调. callback(status, result)."""
        self._callbacks.setdefault(session_id, []).append(callback)

    def create(self, agent_name: str, task: str) -> str:
        """创建一个新 Session."""
        if agent_name not in self._agents:
            raise KeyError(f"Agent '{agent_name}' 未注册。可用: {list(self._agents.keys())}")
        sid = uuid.uuid4().hex[:16]
        session = Session(session_id=sid, agent_name=agent_name, task=task)
        self._store.create(session)
        return sid

    def execute(self, session_id: str):
        """在后台线程执行一个 Session."""
        session = self._store.get(session_id)
        if session is None:
            raise ValueError(f"Session {session_id} 不存在")

        agent = self._agents[session.agent_name]

        def _run():
            self._store.update(session_id, status="running")
            result = agent.run(task=session.task, session_id=session_id)
            status = "completed" if result.success else "failed"
            self._store.update(
                session_id, status=status,
                result=result.output, data=result.data,
            )
            for cb in self._callbacks.pop(session_id, []):
                try:
                    cb(status, result)
                except Exception as e:
                    logger.error(f"Callback error: {e}")
            self._running.pop(session_id, None)

        t = threading.Thread(target=_run, daemon=True)
        self._running[session_id] = t
        t.start()

    def resume(self, session_id: str, new_task: str | None = None) -> AgentResult:
        """恢复一个已存在的 Session — 从转录文件加载历史上下文.

        Args:
            session_id: 要恢复的会话 ID
            new_task: 新的任务描述，None=继续原任务

        Returns:
            AgentResult
        """
        session = self._store.get(session_id)
        if session is None:
            raise ValueError(f"Session {session_id} 不存在")

        agent = self._agents[session.agent_name]
        reader = TranscriptReader(session_id)
        history = reader.read_all()

        if not history:
            # 无历史，等同于全新执行
            task = new_task or session.task
            return agent.run(task=task, session_id=session_id)

        # 构建带历史上下文的消息
        context = {
            "session_id": session_id,
            "history_turns": len(history),
            "previous_task": session.task,
            "last_status": session.status,
        }

        task = new_task or session.task
        logger.info(f"恢复 Session {session_id}: {len(history)} 条历史记录, 任务: {task[:50]}...")
        return agent.run(task=task, context=context, session_id=session_id)

    def run_sync(self, agent_name: str, task: str,
                 session_id: str | None = None) -> AgentResult:
        """同步执行 (阻塞等待)，可选关联 session 进行转录."""
        agent = self._agents[agent_name]
        return agent.run(task=task, session_id=session_id)

    def query(self, session_id: str) -> Session | None:
        """查询 Session 状态."""
        return self._store.get(session_id)

    def get_history(self, session_id: str) -> list[dict]:
        """获取 Session 的对话历史 (用于回放)."""
        reader = TranscriptReader(session_id)
        return reader.read_messages()

    def is_running(self, session_id: str) -> bool:
        return session_id in self._running and self._running[session_id].is_alive()

    def list_active(self) -> list[Session]:
        return self._store.list_active()

    def list_all(self) -> list[Session]:
        """列出所有 Session (包括已完成的)."""
        return self._store.list_all()
