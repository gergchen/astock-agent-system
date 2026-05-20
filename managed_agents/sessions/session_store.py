"""SQLite 持久化 — Session + EventLog.

每个 Session 对应数据库中的一行记录，包含:
- session_id: 唯一标识
- agent_name: 执行的 Agent
- status: pending/running/completed/failed
- task: 任务描述
- result: 执行结果 (JSON)
- created_at / updated_at: 时间戳

EventLog 记录每次操作的详细日志，支持回溯。
"""

import json
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..config import get_config


@dataclass
class Session:
    session_id: str
    agent_name: str
    task: str
    status: str = "pending"  # pending | running | completed | failed
    result: str = ""
    data: dict = field(default_factory=dict)
    created_at: float = 0.0
    updated_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "agent_name": self.agent_name,
            "task": self.task,
            "status": self.status,
            "result": self.result,
            "data": self.data,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class SessionStore:
    """SQLite 会话持久存储 (线程安全)."""

    def __init__(self, db_path: str | None = None):
        if db_path is None:
            db_path = str(get_config().data_dir / "sessions" / "sessions.db")
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _init_db(self):
        with self._lock:
            conn = self._get_conn()
            conn.execute("""CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                agent_name TEXT NOT NULL,
                task TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                result TEXT DEFAULT '',
                data TEXT DEFAULT '{}',
                created_at REAL,
                updated_at REAL
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS event_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                content TEXT DEFAULT '',
                timestamp REAL,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            )""")
            conn.commit()
            conn.close()

    def create(self, session: Session) -> str:
        now = time.time()
        session.created_at = now
        session.updated_at = now
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "INSERT OR REPLACE INTO sessions VALUES (?,?,?,?,?,?,?,?)",
                (session.session_id, session.agent_name, session.task,
                 session.status, session.result, json.dumps(session.data, ensure_ascii=False),
                 session.created_at, session.updated_at),
            )
            self._log_event(conn, session.session_id, "created", session.task)
            conn.commit()
            conn.close()
        return session.session_id

    def update(self, session_id: str, **kwargs):
        with self._lock:
            conn = self._get_conn()
            sets = []
            vals = []
            for k, v in kwargs.items():
                if k == "data":
                    v = json.dumps(v, ensure_ascii=False)
                sets.append(f"{k} = ?")
                vals.append(v)
            sets.append("updated_at = ?")
            vals.append(time.time())
            vals.append(session_id)
            conn.execute(
                f"UPDATE sessions SET {', '.join(sets)} WHERE session_id = ?",
                vals,
            )
            if "status" in kwargs:
                self._log_event(conn, session_id, kwargs["status"], kwargs.get("result", ""))
            conn.commit()
            conn.close()

    def get(self, session_id: str) -> Session | None:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        conn.close()
        if row is None:
            return None
        return Session(
            session_id=row[0], agent_name=row[1], task=row[2],
            status=row[3], result=row[4],
            data=json.loads(row[5]) if row[5] else {},
            created_at=row[6], updated_at=row[7],
        )

    def list_active(self) -> list[Session]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM sessions WHERE status IN ('pending','running') ORDER BY created_at DESC"
        ).fetchall()
        conn.close()
        return [
            Session(sid=row[0], agent_name=row[1], task=row[2],
                    status=row[3], result=row[4],
                    data=json.loads(row[5]) if row[5] else {},
                    created_at=row[6], updated_at=row[7])
            for row in rows
        ]

    def list_all(self) -> list[Session]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM sessions ORDER BY created_at DESC LIMIT 100"
        ).fetchall()
        conn.close()
        return [
            Session(
                session_id=row[0], agent_name=row[1], task=row[2],
                status=row[3], result=row[4],
                data=json.loads(row[5]) if row[5] else {},
                created_at=row[6], updated_at=row[7],
            )
            for row in rows
        ]

    def get_events(self, session_id: str) -> list[dict]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT event_type, content, timestamp FROM event_log WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
        conn.close()
        return [{"type": r[0], "content": r[1], "time": r[2]} for r in rows]

    def _log_event(self, conn, session_id: str, event_type: str, content: str):
        conn.execute(
            "INSERT INTO event_log (session_id, event_type, content, timestamp) VALUES (?,?,?,?)",
            (session_id, event_type, content, time.time()),
        )
