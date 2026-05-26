"""Broker abstraction layer — mock and live trading interfaces."""

import logging

from .base import Account, BrokerBase, Order, OrderSide, OrderStatus, OrderType, Position
from .mock_broker import MockBroker
from .ths_broker import THSBroker

from ..config import get_config

logger = logging.getLogger(__name__)


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

        # 创建验证码识别器（配置了打码平台则自动打码）
        solver = None
        if cfg.captcha_platform == "super_eagle" and cfg.captcha_username and cfg.captcha_password:
            from .captcha_solver import SuperEagleSolver
            solver = SuperEagleSolver(
                username=cfg.captcha_username,
                password=cfg.captcha_password,
                soft_id=cfg.captcha_soft_id or "956802",
            )
            logger.info("超级鹰打码已启用")

        broker: BrokerBase = THSBroker(exe_path=exe, mock_fallback=True,
                                       captcha_solver=solver)
    else:
        broker = MockBroker(initial_cash=cfg.mock_initial_cash)

    broker.connect()
    return broker


__all__ = [
    "Account", "BrokerBase", "Order", "OrderSide", "OrderStatus",
    "OrderType", "Position", "MockBroker", "THSBroker", "create_broker",
]
