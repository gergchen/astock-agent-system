"""A股 Managed Agents 交易平台 — astock_trade"""

__version__ = "0.3.0"

from .config import TradeConfig, get_config
from .exceptions import AStockTradeError, ConfigError, TradeError, RiskViolation, VaultError, BusError
from .risk_engine import (
    RiskEngine,
    RiskDecision,
    RiskDecisionType,
    CheckResult,
    TradeSignal,
    PortfolioSnapshot,
    CircuitBreaker,
    KillSwitch,
    LossAccelerator,
    HARD_LIMITS,
    SOFT_LIMITS,
)
from .crash_recovery import (
    run_crash_recovery,
    RecoveryReport,
    RecoveryResult,
    PositionRecovery,
    OrderReplay,
)
from .regime_engine import (
    RegimeEngine,
    RegimeType,
    RegimeSignal,
)
from .portfolio_optimizer import (
    PortfolioOptimizer,
    PortfolioAllocation,
    StockInfo,
)

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
    # Risk engine
    "RiskEngine",
    "RiskDecision",
    "RiskDecisionType",
    "CheckResult",
    "TradeSignal",
    "PortfolioSnapshot",
    "CircuitBreaker",
    "KillSwitch",
    "LossAccelerator",
    "HARD_LIMITS",
    "SOFT_LIMITS",
    # Crash recovery
    "run_crash_recovery",
    "RecoveryReport",
    "RecoveryResult",
    "PositionRecovery",
    "OrderReplay",
    # Regime engine
    "RegimeEngine",
    "RegimeType",
    "RegimeSignal",
    # Portfolio optimization
    "PortfolioOptimizer",
    "PortfolioAllocation",
    "StockInfo",
]
