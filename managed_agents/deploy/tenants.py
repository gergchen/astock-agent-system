"""多租户隔离 — 每租户独立的存储、限额、Agent 白名单."""

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import get_config

logger = logging.getLogger(__name__)


@dataclass
class Tenant:
    tenant_id: str
    name: str = ""
    agent_whitelist: list[str] = field(default_factory=list)  # [] = all
    max_concurrent_sessions: int = 10
    max_sessions_per_hour: int = 50
    max_tokens_per_day: int = 1_000_000
    created_at: float = field(default_factory=time.time)

    @property
    def data_dir(self) -> Path:
        return get_config().data_dir / "tenants" / self.tenant_id

    @property
    def session_db(self) -> Path:
        return self.data_dir / "sessions.db"

    @property
    def transcript_dir(self) -> Path:
        return self.data_dir / "transcripts"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.transcript_dir.mkdir(parents=True, exist_ok=True)


class TenantManager:
    """多租户管理器."""

    def __init__(self):
        self._tenants: dict[str, Tenant] = {}

    def create(self, tenant_id: str, name: str = "",
               agent_whitelist: list[str] | None = None,
               max_concurrent: int = 10) -> Tenant:
        if tenant_id in self._tenants:
            raise ValueError(f"Tenant '{tenant_id}' already exists")
        t = Tenant(
            tenant_id=tenant_id, name=name,
            agent_whitelist=agent_whitelist or [],
            max_concurrent_sessions=max_concurrent,
        )
        t.ensure_dirs()
        self._tenants[tenant_id] = t
        logger.info(f"Tenant created: {tenant_id} ({name})")
        return t

    def get(self, tenant_id: str) -> Tenant:
        if tenant_id not in self._tenants:
            raise KeyError(f"Tenant '{tenant_id}' not found")
        return self._tenants[tenant_id]

    def remove(self, tenant_id: str) -> None:
        if tenant_id in self._tenants:
            del self._tenants[tenant_id]
            logger.info(f"Tenant removed: {tenant_id}")

    def list_all(self) -> list[Tenant]:
        return list(self._tenants.values())

    def can_use_agent(self, tenant_id: str, agent_name: str) -> bool:
        """检查租户是否有权使用某 Agent."""
        t = self.get(tenant_id)
        if not t.agent_whitelist:
            return True
        return agent_name in t.agent_whitelist

    def get_session_count(self, tenant_id: str) -> int:
        """查询租户当前活跃会话数."""
        t = self.get(tenant_id)
        if not t.session_db.exists():
            return 0
        import sqlite3
        conn = sqlite3.connect(str(t.session_db))
        count = conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE status IN ('pending','running')"
        ).fetchone()[0]
        conn.close()
        return count

    def check_rate_limit(self, tenant_id: str) -> bool:
        """检查租户速率限制."""
        t = self.get(tenant_id)
        active = self.get_session_count(tenant_id)
        return active < t.max_concurrent_sessions


_tenant_manager: TenantManager | None = None


def get_tenant_manager() -> TenantManager:
    global _tenant_manager
    if _tenant_manager is None:
        _tenant_manager = TenantManager()
    return _tenant_manager
