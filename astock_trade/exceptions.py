class AStockTradeError(Exception):
    """Base exception for astock_trade."""


class ConfigError(AStockTradeError):
    """Configuration error."""


class TradeError(AStockTradeError):
    """Trade execution error."""


class RiskViolation(AStockTradeError):
    """Risk limit exceeded."""


class VaultError(AStockTradeError):
    """Key vault access error."""


class BusError(AStockTradeError):
    """Message bus error."""
