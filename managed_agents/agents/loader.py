"""Agent 定义加载器 — 解析 .claude/agents/*.md YAML frontmatter.

每个 .md 文件的 YAML 头部定义 Agent 的:
- name: 唯一标识
- description: 简要描述
- model: 使用的模型
- skills: 技能列表
- tools: 工具列表

Markdown body 作为 system prompt。
"""

import logging
import yaml
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class AgentDefinition:
    name: str
    description: str = ""
    model: str = "deepseek-v4-pro"
    skills: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    system_prompt: str = ""       # Markdown body
    source_file: str = ""         # 来源文件


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from markdown text.

    Returns (frontmatter_dict, body_text).
    """
    text = text.strip()
    if not text.startswith("---"):
        return {}, text

    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text

    fm = yaml.safe_load(parts[1]) or {}
    body = parts[2].strip()
    return fm, body


def load_agent_definition(filepath: Path) -> AgentDefinition | None:
    """从 .md 文件加载单个 Agent 定义."""
    try:
        text = filepath.read_text(encoding="utf-8")
        fm, body = _parse_frontmatter(text)

        if "name" not in fm:
            logger.warning(f"Skipping {filepath.name}: no 'name' in frontmatter")
            return None

        return AgentDefinition(
            name=fm["name"],
            description=fm.get("description", ""),
            model=fm.get("model", "deepseek-v4-pro"),
            skills=fm.get("skills", []),
            tools=fm.get("tools", []),
            system_prompt=body,
            source_file=str(filepath),
        )
    except Exception as e:
        logger.error(f"Failed to load {filepath}: {e}")
        return None


def load_all_agents(agents_dir: Path | None = None) -> dict[str, AgentDefinition]:
    """加载 agents 目录下所有 .md 文件.

    Returns {name: AgentDefinition}
    """
    if agents_dir is None:
        agents_dir = Path(__file__).parent.parent.parent / ".claude" / "agents"

    agents = {}
    if not agents_dir.exists():
        logger.warning(f"Agents directory not found: {agents_dir}")
        return agents

    for f in sorted(agents_dir.glob("*.md")):
        agent_def = load_agent_definition(f)
        if agent_def:
            agents[agent_def.name] = agent_def
            logger.info(f"Loaded agent: {agent_def.name} ({f.name})")

    return agents


def load_trading_agents() -> dict[str, AgentDefinition]:
    """只加载交易相关的 Agent 定义."""
    all_agents = load_all_agents()
    trading_names = {
        "morning-analyst", "researcher-trader", "day-trader",
        "risk-officer", "portfolio-manager",
    }
    return {k: v for k, v in all_agents.items() if k in trading_names}
