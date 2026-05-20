"""AgentRegistry — 全局 Agent 注册中心.

管理所有 Agent 实例的生命周期:
- register: 注册一个 Agent
- get: 按名字获取 Agent
- list_all: 列出所有已注册 Agent
"""

import logging
from typing import Type

from .base import BaseAgent

logger = logging.getLogger(__name__)


class AgentRegistry:
    """全局 Agent 注册中心 (单例)."""

    _instance: "AgentRegistry | None" = None

    def __init__(self):
        self._agents: dict[str, BaseAgent] = {}

    @classmethod
    def get_instance(cls) -> "AgentRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def register(self, agent: BaseAgent) -> None:
        if agent.name in self._agents:
            logger.warning(f"Agent '{agent.name}' 已存在，将覆盖。")
        self._agents[agent.name] = agent
        logger.info(f"Agent '{agent.name}' ({agent.role}) 已注册。")

    def get(self, name: str) -> BaseAgent:
        agent = self._agents.get(name)
        if agent is None:
            raise KeyError(f"Agent '{name}' 未注册。可用: {list(self._agents.keys())}")
        return agent

    def list_all(self) -> list[dict]:
        return [
            {"name": a.name, "role": a.role, "skills": list(a._skills.keys())}
            for a in self._agents.values()
        ]

    def remove(self, name: str) -> None:
        if name in self._agents:
            del self._agents[name]
            logger.info(f"Agent '{name}' 已注销。")

    def clear(self) -> None:
        self._agents.clear()
