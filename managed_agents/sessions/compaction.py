"""三层压缩管道 — 解决长任务上下文丢失（余晖问题）.

MicroCompact: 保留边界 + 最后 N 轮 (触发: 手动)
AutoCompact:  保留边界 + 最近 N 轮摘要 (触发: token ≥ 100K)
FullCompact:  全量摘要 + 关键信息提取 (触发: token ≥ 200K, 上限 50K)
"""

import logging
from dataclasses import dataclass, field

from .transcript import TranscriptEvent, TranscriptReader

logger = logging.getLogger(__name__)

# 近似: 英文 ~0.75 tokens/char, 中文 ~1.5 tokens/char
TOKENS_PER_CHAR = 1.2


def estimate_tokens(messages: list[dict]) -> int:
    """估算消息列表的总 token 数."""
    total = 0
    for m in messages:
        total += int(len(m.get("content", "")) * TOKENS_PER_CHAR)
    return total


@dataclass
class CompactionResult:
    """压缩结果."""
    messages: list[dict]
    compacted_count: int      # 被压缩的事件数
    summary: str = ""         # 压缩摘要 (FullCompact 时填充)
    level: str = "none"       # none | micro | auto | full


class Compactor:
    """会话压缩器."""

    def __init__(self, max_tokens: int = 50000, auto_threshold: int = 100000):
        self.max_tokens = max_tokens
        self.auto_threshold = auto_threshold

    def maybe_compact(self, messages: list[dict]) -> CompactionResult:
        """根据 token 数自动选择压缩策略."""
        tokens = estimate_tokens(messages)
        if tokens < self.auto_threshold:
            return CompactionResult(messages=messages, compacted_count=0, level="none")

        if tokens < 200000:
            return self.micro_compact(messages)

        return self.full_compact(messages)

    def micro_compact(self, messages: list[dict]) -> CompactionResult:
        """微观压缩: 保留边界 + 最后 N 轮.

        保留:
        - 前 2 条消息 (任务定义)
        - 后 10 条消息 (最近上下文)
        - 中间每隔 K 条保留 1 条作为锚点
        """
        if len(messages) <= 12:
            return CompactionResult(messages=messages, compacted_count=0, level="micro")

        head = messages[:2]
        tail = messages[-10:]
        middle = messages[2:-10]
        stride = max(1, len(middle) // 5)
        anchors = middle[::stride]

        compacted = head + anchors + tail
        dropped = len(messages) - len(compacted)

        logger.info(f"MicroCompact: {len(messages)} -> {len(compacted)} events (dropped {dropped})")
        return CompactionResult(messages=compacted, compacted_count=dropped, level="micro")

    def full_compact(self, messages: list[dict]) -> CompactionResult:
        """全量压缩: 提取摘要 + 保留最近上下文.

        产出:
        - 一条系统消息包含历史摘要
        - 最近 4 轮完整对话
        - 上限 50000 tokens
        """
        if len(messages) <= 6:
            return CompactionResult(messages=messages, compacted_count=0, level="full")

        # 提取用户消息生成摘要
        user_messages = [m for m in messages if m.get("role") == "user"]
        recent_turns = messages[-8:]

        summary_parts = []
        for m in user_messages[:-4]:
            content = m.get("content", "")
            if len(content) > 200:
                content = content[:200] + "..."
            summary_parts.append(content)

        summary = "历史摘要:\n" + "\n".join(f"- {s}" for s in summary_parts[-20:])

        compacted = [
            {"role": "user", "content": summary},
        ] + recent_turns

        # 硬截断到 max_tokens
        while estimate_tokens(compacted) > self.max_tokens and len(recent_turns) > 2:
            recent_turns = recent_turns[2:]
            compacted = [{"role": "user", "content": summary}] + recent_turns

        dropped = len(messages) - len(compacted)
        logger.info(f"FullCompact: {len(messages)} -> {len(compacted)} events (summary + {len(recent_turns)} recent)")
        return CompactionResult(
            messages=compacted, compacted_count=dropped,
            summary=summary, level="full",
        )

    @staticmethod
    def from_transcript(session_id: str, max_turns: int = 500) -> list[dict]:
        """从转录文件恢复消息列表 (用于断线重连)."""
        reader = TranscriptReader(session_id)
        return reader.read_messages(max_turns=max_turns)
