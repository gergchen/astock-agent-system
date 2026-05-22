"""Unified configuration — single source of truth for all modules.

Covers: astock_trade, managed_agents, and (delegated) astock_data.

Env-var overrides use ATRADE_ prefix for trade settings, AGENT_ for agent settings.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path


def _load_dotenv(path: str | None = None) -> None:
    """Load .env from project root into os.environ (no external deps)."""
    if path is None:
        path = os.path.join(os.path.dirname(__file__), "..", ".env")
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip("\"'")
            if key not in os.environ:  # 不覆盖已存在的显式赋值
                os.environ[key] = val


# Auto-load .env on import
_load_dotenv()


def _env_bool(key: str, default: bool = False) -> bool:
    val = os.environ.get(key)
    if val is None:
        return default
    return val.lower() in ("1", "true", "yes")


# ═══════════════════════════════════════════════════════════════════
# Unified TradeConfig
# ═══════════════════════════════════════════════════════════════════


@dataclass
class TradeConfig:
    """Singleton configuration for the whole A-stock trading system."""

    # ── Project ───────────────────────────────────────────────
    project_dir: Path = field(default_factory=lambda: Path(__file__).parent.parent)
    data_dir: Path = field(default_factory=lambda: Path("data"))

    # ── Directories (astock_trade) ─────────────────────────────
    trade_journal_dir: Path = field(default_factory=lambda: Path("data/trade_journal"))
    strategies_dir: Path = field(default_factory=lambda: Path("data/strategies"))
    watchlists_dir: Path = field(default_factory=lambda: Path("data/watchlists"))
    alerts_dir: Path = field(default_factory=lambda: Path("data/alerts"))
    bus_dir: Path = field(default_factory=lambda: Path("data/bus"))
    vault_dir: Path = field(default_factory=lambda: Path.home() / ".astock_trade" / "vault")

    # ── Directories (managed_agents) ──────────────────────────
    agents_data_dir: Path = field(default_factory=lambda: Path("managed_agents_data"))
    sessions_dir: Path = field(default_factory=lambda: Path("managed_agents_data/sessions"))
    memory_dir: Path = field(default_factory=lambda: Path("managed_agents_data/memory"))
    agent_vaults_dir: Path = field(default_factory=lambda: Path("managed_agents_data/vaults"))
    agent_logs_dir: Path = field(default_factory=lambda: Path("managed_agents_data/logs"))

    # ── Scan defaults ─────────────────────────────────────────
    intraday_scan_interval_minutes: int = 5
    quote_poll_interval_seconds: int = 60

    # ── Alert thresholds ──────────────────────────────────────
    price_breakout_pct: float = 3.0
    volume_spike_multiplier: float = 2.0
    northbound_anomaly_yi: float = 5.0  # 亿元

    # ── Risk defaults ─────────────────────────────────────────
    max_position_pct: float = 0.30
    max_daily_drawdown_pct: float = 0.05

    # ── Trading hours (Beijing time) ──────────────────────────
    morning_open: str = "09:30"
    morning_close: str = "11:30"
    afternoon_open: str = "13:00"
    afternoon_close: str = "15:00"

    # ── LLM (managed_agents) ──────────────────────────────────
    llm_base_url: str = os.environ.get("ANTHROPIC_BASE_URL", "https://api.deepseek.com/anthropic")
    llm_api_key: str = os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
    llm_model: str = "deepseek-v4-pro"
    llm_max_tokens: int = 4096

    # ── Agent defaults ────────────────────────────────────────
    agent_max_retries: int = 3
    agent_timeout: int = 300  # seconds per task
    agent_max_workers: int = 4

    # ── Session ───────────────────────────────────────────────
    session_max_idle: int = 3600
    session_cleanup_interval: int = 600

    # ── Sentinel ──────────────────────────────────────────────
    sentinel_scan_interval: int = 120
    sentinel_alerts_hotspot: bool = True
    sentinel_alerts_northbound: bool = True
    sentinel_alerts_volume: bool = True

    # ── Risk Engine — Kill Switch ─────────────────────────────
    kill_switch_auto_pull_on_loss_acceleration: bool = True
    loss_acceleration_window_minutes: int = 15
    loss_acceleration_threshold: int = 3

    # ── Regime Engine ─────────────────────────────────────────
    regime_default_index: str = "000300"
    regime_lookback_days: int = 60
    regime_auto_adjust_risk: bool = True

    # ── Portfolio Optimization ────────────────────────────────
    portfolio_max_single_pct: float = 0.20
    portfolio_max_sector_pct: float = 0.30
    portfolio_max_total_pct: float = 0.70
    portfolio_max_count: int = 8
    portfolio_min_cash_pct: float = 0.30

    # ── Alpha Evaluation ──────────────────────────────────────
    alpha_min_periods: int = 30

    @property
    def sentinel_alerts(self) -> dict:
        """Backward-compatible dict form of sentinel alert toggles."""
        return {
            "hotspot_change": self.sentinel_alerts_hotspot,
            "northbound_alert": self.sentinel_alerts_northbound,
            "volume_spike": self.sentinel_alerts_volume,
        }

    # ── Notification — 飞书 ───────────────────────────────────
    feishu_webhook_url: str = os.environ.get("FEISHU_WEBHOOK_URL", "")
    feishu_app_id: str = os.environ.get("FEISHU_APP_ID", "")
    feishu_app_secret: str = os.environ.get("FEISHU_APP_SECRET", "")

    # ── Logging ────────────────────────────────────────────────
    log_level: str = os.environ.get("ATRADE_LOG_LEVEL", "INFO")
    log_dir: Path = field(default_factory=lambda: Path("data/logs"))
    log_file_max_mb: int = 10
    log_file_backups: int = 5

    def __post_init__(self):
        # ── Env-var overrides (ATRADE_ prefix for trade settings) ─
        for name in self.__dataclass_fields__:
            env_key = f"ATRADE_{name.upper()}"
            if env_key in os.environ:
                self._apply_env(name, os.environ[env_key])

        # ── AGENT_ prefix for agent settings ──────────────────
        agent_env_map = {
            "AGENT_MAX_RETRIES": "agent_max_retries",
            "AGENT_TIMEOUT": "agent_timeout",
            "AGENT_MAX_WORKERS": "agent_max_workers",
            "AGENT_LLM_MODEL": "llm_model",
            "AGENT_LOG_LEVEL": "log_level",
            "AGENT_SENTINEL_INTERVAL": "sentinel_scan_interval",
        }
        for env_key, attr in agent_env_map.items():
            if env_key in os.environ:
                self._apply_env(attr, os.environ[env_key])

        # ── Ensure directories exist ──────────────────────────
        for attr_name in [
            "data_dir", "trade_journal_dir", "strategies_dir",
            "watchlists_dir", "alerts_dir", "bus_dir",
            "agents_data_dir", "sessions_dir", "memory_dir",
            "agent_vaults_dir", "agent_logs_dir", "log_dir",
        ]:
            d = getattr(self, attr_name, None)
            if isinstance(d, Path):
                d.mkdir(parents=True, exist_ok=True)

    def _apply_env(self, name: str, val: str):
        current = getattr(self, name)
        if isinstance(current, bool):
            setattr(self, name, val.lower() in ("1", "true", "yes"))
        elif isinstance(current, int):
            setattr(self, name, int(val))
        elif isinstance(current, float):
            setattr(self, name, float(val))
        elif isinstance(current, Path):
            setattr(self, name, Path(val))
        else:
            setattr(self, name, val)


_config: TradeConfig | None = None


def get_config() -> TradeConfig:
    global _config
    if _config is None:
        _config = TradeConfig()
    return _config


def reset_config() -> None:
    global _config
    _config = None
