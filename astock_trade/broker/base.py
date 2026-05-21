"""Abstract broker interface — all brokers must implement this."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


@dataclass
class Order:
    symbol: str
    side: OrderSide
    price: float
    volume: int
    order_type: OrderType = OrderType.LIMIT
    order_id: Optional[str] = None
    status: OrderStatus = OrderStatus.PENDING
    filled_volume: int = 0
    filled_price: float = 0.0
    created_at: Optional[datetime] = None
    reject_reason: Optional[str] = None


@dataclass
class Position:
    symbol: str
    volume: int
    avg_cost: float
    current_price: float = 0.0
    market_value: float = 0.0
    pnl: float = 0.0
    pnl_pct: float = 0.0


@dataclass
class Account:
    cash: float
    frozen: float = 0.0
    total_assets: float = 0.0
    positions: list[Position] = None

    def __post_init__(self):
        if self.positions is None:
            self.positions = []


class BrokerBase(ABC):
    """Abstract broker defining the trading interface."""

    @abstractmethod
    def connect(self) -> bool:
        """Connect to broker. Returns True on success."""
        ...

    @abstractmethod
    def disconnect(self) -> None:
        """Disconnect from broker."""
        ...

    @abstractmethod
    def get_account(self) -> Account:
        """Get current account status."""
        ...

    @abstractmethod
    def get_positions(self) -> list[Position]:
        """Get current positions."""
        ...

    @abstractmethod
    def place_order(self, symbol: str, side: OrderSide, price: float,
                    volume: int, order_type: OrderType = OrderType.LIMIT) -> Order:
        """Place an order. Returns the Order object with order_id."""
        ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an order. Returns True on success."""
        ...

    @abstractmethod
    def get_order(self, order_id: str) -> Optional[Order]:
        """Get order status by ID."""
        ...

    @abstractmethod
    def get_orders(self, symbol: Optional[str] = None) -> list[Order]:
        """Get all orders, optionally filtered by symbol."""
        ...
