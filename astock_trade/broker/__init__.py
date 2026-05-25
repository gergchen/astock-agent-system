"""Broker abstraction layer — mock and live trading interfaces."""

from .base import Account, BrokerBase, Order, OrderSide, OrderStatus, OrderType, Position
from .mock_broker import MockBroker
from .ths_broker import THSBroker

from ..config import get_config


def create_broker(broker_type: str | None = None,
                  ths_exe_path: str | None = None) -> BrokerBase:
    """Create and connect a broker based on config or explicit arguments.

    Args:
        broker_type: "mock" or "ths". If None, reads from TradeConfig.
        ths_exe_path: Path to THS xiadan.exe. If None, reads from config
                      or lets THSBroker auto-detect.

    Returns:
        A connected BrokerBase instance.
    """
    cfg = get_config()
    bt = broker_type or cfg.broker_type

    if bt == "ths":
        exe = ths_exe_path or cfg.ths_exe_path
        broker: BrokerBase = THSBroker(exe_path=exe, mock_fallback=True)
    else:
        broker = MockBroker(initial_cash=1_000_000.0)

    broker.connect()
    return broker


__all__ = [
    "Account", "BrokerBase", "Order", "OrderSide", "OrderStatus",
    "OrderType", "Position", "MockBroker", "THSBroker", "create_broker",
]
