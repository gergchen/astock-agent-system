"""Trading system configuration — singleton dataclass with env-var overrides."""

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TradeConfig:
    """Singleton configuration for astock_trade."""

    # Data directories
    data_dir: Path = field(default_factory=lambda: Path("data"))
    trade_journal_dir: Path = field(default_factory=lambda: Path("data/trade_journal"))
    strategies_dir: Path = field(default_factory=lambda: Path("data/strategies"))
    watchlists_dir: Path = field(default_factory=lambda: Path("data/watchlists"))
    alerts_dir: Path = field(default_factory=lambda: Path("data/alerts"))
    bus_dir: Path = field(default_factory=lambda: Path("data/bus"))
    vault_dir: Path = field(default_factory=lambda: Path.home() / ".astock_trade" / "vault")

    # Scan defaults
    intraday_scan_interval_minutes: int = 5
    quote_poll_interval_seconds: int = 60

    # Alert thresholds
    price_breakout_pct: float = 3.0
    volume_spike_multiplier: float = 2.0
    northbound_anomaly_yi: float = 5.0  # 亿元

    # Risk defaults
    max_position_pct: float = 0.30
    max_daily_drawdown_pct: float = 0.05

    # Trading hours (Beijing time)
    morning_open: str = "09:30"
    morning_close: str = "11:30"
    afternoon_open: str = "13:00"
    afternoon_close: str = "15:00"

    def __post_init__(self):
        # Env overrides
        for name in self.__dataclass_fields__:
            env_key = f"ATRADE_{name.upper()}"
            if env_key in os.environ:
                val = os.environ[env_key]
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

        # Ensure directories exist
        for d in [self.data_dir, self.trade_journal_dir, self.strategies_dir,
                   self.watchlists_dir, self.alerts_dir, self.bus_dir]:
            d.mkdir(parents=True, exist_ok=True)


_config: TradeConfig | None = None


def get_config() -> TradeConfig:
    global _config
    if _config is None:
        _config = TradeConfig()
    return _config
