"""Mock broker — simulates trading for testing and paper trading."""

import uuid
from datetime import datetime
from typing import Optional

from .base import (
    Account, BrokerBase, Order, OrderSide, OrderStatus, OrderType, Position,
)


class MockBroker(BrokerBase):
    """In-memory simulated broker for testing and paper trading."""

    def __init__(self, initial_cash: float = 1_000_000.0):
        self._cash = initial_cash
        self._frozen = 0.0
        self._positions: dict[str, Position] = {}
        self._orders: dict[str, Order] = {}
        self._connected = False

    def connect(self) -> bool:
        self._connected = True
        return True

    def disconnect(self) -> None:
        self._connected = False

    def get_account(self) -> Account:
        positions = list(self._positions.values())
        position_value = sum(p.market_value for p in positions)
        return Account(
            cash=round(self._cash, 2),
            frozen=round(self._frozen, 2),
            total_assets=round(self._cash + self._frozen + position_value, 2),
            positions=positions,
        )

    def get_positions(self) -> list[Position]:
        return list(self._positions.values())

    def place_order(self, symbol: str, side: OrderSide, price: float,
                    volume: int, order_type: OrderType = OrderType.LIMIT) -> Order:
        order_id = str(uuid.uuid4())[:8]
        order = Order(
            symbol=symbol,
            side=side,
            price=price,
            volume=volume,
            order_type=order_type,
            order_id=order_id,
            status=OrderStatus.FILLED,  # mock fills immediately
            filled_volume=volume,
            filled_price=price,
            created_at=datetime.now(),
        )
        self._orders[order_id] = order

        amount = price * volume
        if side == OrderSide.BUY:
            self._cash -= amount
            if symbol in self._positions:
                pos = self._positions[symbol]
                total_volume = pos.volume + volume
                pos.avg_cost = ((pos.avg_cost * pos.volume) + amount) / total_volume
                pos.volume = total_volume
                pos.market_value = pos.volume * price
            else:
                self._positions[symbol] = Position(
                    symbol=symbol, volume=volume, avg_cost=price,
                    current_price=price, market_value=amount, pnl=0.0, pnl_pct=0.0,
                )
        else:
            self._cash += amount
            if symbol in self._positions:
                pos = self._positions[symbol]
                pos.volume -= volume
                if pos.volume <= 0:
                    del self._positions[symbol]
                else:
                    pos.market_value = pos.volume * price

        return order

    def cancel_order(self, order_id: str) -> bool:
        if order_id in self._orders:
            self._orders[order_id].status = OrderStatus.CANCELLED
            return True
        return False

    def get_order(self, order_id: str) -> Optional[Order]:
        return self._orders.get(order_id)

    def get_orders(self, symbol: Optional[str] = None) -> list[Order]:
        orders = list(self._orders.values())
        if symbol:
            orders = [o for o in orders if o.symbol == symbol]
        return orders

    def update_position_prices(self, quotes: dict[str, float]) -> None:
        """Update current prices for positions (used with market quotes)."""
        for symbol, price in quotes.items():
            if symbol in self._positions:
                pos = self._positions[symbol]
                pos.current_price = price
                pos.market_value = pos.volume * price
                pos.pnl = round((price - pos.avg_cost) * pos.volume, 2)
                pos.pnl_pct = round((price / pos.avg_cost - 1) * 100, 2)
