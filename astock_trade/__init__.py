"""A股 Managed Agents 交易平台 — astock_trade"""

__version__ = "0.1.0"

from .config import TradeConfig, get_config
from .exceptions import AStockTradeError, ConfigError, TradeError, RiskViolation, VaultError, BusError

__all__ = [
    "__version__",
    "TradeConfig",
    "get_config",
    "AStockTradeError",
    "ConfigError",
    "TradeError",
    "RiskViolation",
    "VaultError",
    "BusError",
]
