"""Tests for exceptions module."""

from astock_trade.exceptions import (
    AStockTradeError, ConfigError, TradeError, RiskViolation, VaultError, BusError,
)


class TestExceptions:
    def test_hierarchy(self):
        assert issubclass(ConfigError, AStockTradeError)
        assert issubclass(TradeError, AStockTradeError)
        assert issubclass(RiskViolation, AStockTradeError)
        assert issubclass(VaultError, AStockTradeError)
        assert issubclass(BusError, AStockTradeError)

    def test_messages(self):
        e = TradeError("insufficient funds")
        assert str(e) == "insufficient funds"

    def test_base_is_exception(self):
        assert issubclass(AStockTradeError, Exception)
