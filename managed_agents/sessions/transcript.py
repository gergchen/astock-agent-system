"""JSONL 对话转录 — 记录每个 Session 的完整对话历史.

每行一个 TranscriptEvent JSON，支持:
- 增量追加 (append-only)
- 100MB 自动分片
- 批量写入 (100ms flush interval)
"""

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..config import get_config

TRANSCRIPT_VERSION = 1


@dataclass
class TranscriptEvent:
    role: str          # system | user | assistant | tool_result
    content: str
    timestamp: float = field(default_factory=time.time)
    metadata: dict = field(default_factory=dict)

    def to_line(self) -> str:
        return json.dumps({
            "v": TRANSCRIPT_VERSION,
            "ts": self.timestamp,
            "role": self.role,
            "content": self.content,
            "meta": self.metadata,
        }, ensure_ascii=False) + "\n"


class TranscriptWriter:
    """JSONL 转录写入器."""

    def __init__(self, session_id: str, base_dir: Path | None = None):
        if base_dir is None:
            base_dir = get_config().data_dir / "transcripts"
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.session_id = session_id
        self._chunk_index = 0
        self._line_count = 0
        self._buffer: list[str] = []
        self._last_flush = time.time()
        self._file = self._open_chunk()

    def _chunk_path(self) -> Path:
        return self.base_dir / f"{self.session_id}_{self._chunk_index:04d}.jsonl"

    def _open_chunk(self):
        return open(self._chunk_path(), "a", encoding="utf-8")

    def append(self, event: TranscriptEvent) -> None:
        line = event.to_line()
        self._buffer.append(line)
        self._line_count += 1

        if self._should_flush():
            self.flush()

    def _should_flush(self) -> bool:
        if len(self._buffer) >= 50:
            return True
        if time.time() - self._last_flush >= 0.1:
            return True
        if self._file.tell() > 100 * 1024 * 1024:  # 100MB
            return True
        return False

    def flush(self) -> None:
        if not self._buffer:
            return
        self._file.writelines(self._buffer)
        self._file.flush()
        self._buffer.clear()
        self._last_flush = time.time()

        if self._file.tell() > 100 * 1024 * 1024:
            self._file.close()
            self._chunk_index += 1
            self._file = self._open_chunk()

    def close(self) -> None:
        self.flush()
        self._file.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class TranscriptReader:
    """JSONL 转录读取器 — 支持断点恢复."""

    def __init__(self, session_id: str, base_dir: Path | None = None):
        if base_dir is None:
            base_dir = get_config().data_dir / "transcripts"
        self.base_dir = Path(base_dir)
        self.session_id = session_id

    def read_all(self) -> list[TranscriptEvent]:
        events = []
        for chunk_path in self._chunk_files():
            with open(chunk_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        events.append(TranscriptEvent(
                            role=data["role"],
                            content=data["content"],
                            timestamp=data.get("ts", 0),
                            metadata=data.get("meta", {}),
                        ))
                    except json.JSONDecodeError:
                        continue
        return events

    def read_messages(self, max_turns: int | None = None) -> list[dict]:
        """读取转录并转换为 LLM messages 格式.

        Args:
            max_turns: 限制返回最近 N 轮对话 (user+assistant pairs)

        Returns:
            [{"role": "user", "content": "..."}, ...]
        """
        events = self.read_all()
        messages = []
        for e in events:
            if e.role in ("user", "assistant"):
                messages.append({"role": e.role, "content": e.content})

        if max_turns and len(messages) > max_turns:
            messages = messages[-max_turns:]

        return messages

    def _chunk_files(self) -> list[Path]:
        pattern = f"{self.session_id}_*.jsonl"
        return sorted(self.base_dir.glob(pattern))
