"""Managed Agents 全局配置."""

import os
from pathlib import Path
from dataclasses import dataclass, field


def _load_dotenv() -> None:
    """加载项目根目录 .env 文件到 os.environ（不覆盖已有值）."""
    env_file = Path(__file__).parent.parent / ".env"
    if not env_file.is_file():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


_load_dotenv()


@dataclass
class Config:
    project_dir: Path = field(default_factory=lambda: Path(__file__).parent.parent)
    data_dir: Path = field(default_factory=lambda: Path(__file__).parent.parent / "managed_agents_data")

    # LLM
    llm_base_url: str = os.environ.get("ANTHROPIC_BASE_URL", "https://api.deepseek.com/anthropic")
    llm_api_key: str = os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
    llm_model: str = "deepseek-v4-pro"
    llm_max_tokens: int = 4096

    # Agent defaults
    agent_max_retries: int = 3
    agent_timeout: int = 300  # seconds per task

    # Session
    session_max_idle: int = 3600  # 1 hour
    session_cleanup_interval: int = 600

    # Sentinel
    sentinel_scan_interval: int = 120  # seconds between market scans
    sentinel_alerts: dict = field(default_factory=lambda: {
        "hotspot_change": True,
        "northbound_alert": True,
        "volume_spike": True,
    })

    # Notification — 飞书 webhook 主通道
    feishu_webhook_url: str = os.environ.get("FEISHU_WEBHOOK_URL", "")
    feishu_app_id: str = os.environ.get("FEISHU_APP_ID", "")
    feishu_app_secret: str = os.environ.get("FEISHU_APP_SECRET", "")

    def __post_init__(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "sessions").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "memory").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "vaults").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "logs").mkdir(parents=True, exist_ok=True)


_config: Config | None = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = Config()
    return _config
