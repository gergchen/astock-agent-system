"""MemoryStore — 三层跨会话记忆 (SQLite).

Tiers:
- user: 用户偏好、关注股票列表
- project: 策略参数、风控阈值
- session: 每次分析的结论摘要（自动蒸馏）
"""

import json
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..config import get_config


@dataclass
class MemoryEntry:
    key: str
    value: str
    tier: str = "session"  # user | project | session
    tags: list[str] = field(default_factory=list)
    created_at: float = 0.0
    updated_at: float = 0.0


class MemoryStore:
    """三层记忆存储 (线程安全)."""

    _instance: "MemoryStore | None" = None

    def __init__(self, db_path: str | None = None):
        if db_path is None:
            db_path = str(get_config().data_dir / "memory" / "memory.db")
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    @classmethod
    def get_instance(cls) -> "MemoryStore":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _init_db(self):
        with self._lock:
            conn = self._get_conn()
            conn.execute("""CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                tier TEXT DEFAULT 'session',
                tags TEXT DEFAULT '[]',
                created_at REAL,
                updated_at REAL
            )""")
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_key_tier ON memories(key, tier)")
            conn.commit()
            conn.close()

    def put(self, key: str, value: str, tier: str = "session",
            tags: list[str] | None = None) -> None:
        """写入或更新一条记忆."""
        now = time.time()
        tags_json = json.dumps(tags or [], ensure_ascii=False)
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                """INSERT INTO memories (key, value, tier, tags, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(key, tier) DO UPDATE SET
                   value = excluded.value,
                   tags = excluded.tags,
                   updated_at = excluded.updated_at""",
                (key, value, tier, tags_json, now, now),
            )
            conn.commit()
            conn.close()

    def get(self, key: str, tier: str = "session") -> str | None:
        """读取一条记忆."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT value FROM memories WHERE key = ? AND tier = ?",
            (key, tier),
        ).fetchone()
        conn.close()
        return row[0] if row else None

    def list_by_tier(self, tier: str) -> list[dict]:
        """列出某层级的全部记忆."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT key, value, tier, tags, updated_at FROM memories WHERE tier = ? ORDER BY updated_at DESC",
            (tier,),
        ).fetchall()
        conn.close()
        return [
            {"key": r[0], "value": r[1], "tier": r[2],
             "tags": json.loads(r[3]) if r[3] else [],
             "updated_at": r[4]}
            for r in rows
        ]

    def search(self, query: str, tier: str | None = None) -> list[dict]:
        """模糊搜索记忆."""
        conn = self._get_conn()
        if tier:
            rows = conn.execute(
                "SELECT key, value, tier, tags, updated_at FROM memories WHERE tier = ? AND (key LIKE ? OR value LIKE ?) ORDER BY updated_at DESC",
                (tier, f"%{query}%", f"%{query}%"),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT key, value, tier, tags, updated_at FROM memories WHERE key LIKE ? OR value LIKE ? ORDER BY updated_at DESC",
                (f"%{query}%", f"%{query}%"),
            ).fetchall()
        conn.close()
        return [
            {"key": r[0], "value": r[1], "tier": r[2],
             "tags": json.loads(r[3]) if r[3] else [],
             "updated_at": r[4]}
            for r in rows
        ]

    def delete(self, key: str, tier: str = "session") -> bool:
        """删除一条记忆."""
        with self._lock:
            conn = self._get_conn()
            cursor = conn.execute(
                "DELETE FROM memories WHERE key = ? AND tier = ?",
                (key, tier),
            )
            conn.commit()
            deleted = cursor.rowcount > 0
            conn.close()
            return deleted

    def save_session_summary(self, session_id: str, summary: str,
                             tags: list[str] | None = None) -> None:
        """保存 Session 分析摘要（自动蒸馏入口）."""
        self.put(
            key=f"session:{session_id}",
            value=summary,
            tier="session",
            tags=tags or [],
        )
