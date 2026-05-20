"""Tests for broker modules."""

import pytest

from astock_trade.broker.base import (
    Account, BrokerBase, Order, OrderSide, OrderStatus, OrderType, Position,
)
from astock_trade.broker.mock_broker import MockBroker


class TestOrderModel:
    def test_order_defaults(self):
        order = Order(symbol="600519", side=OrderSide.BUY, price=100.0, volume=200)
        assert order.status == OrderStatus.PENDING
        assert order.filled_volume == 0
        assert order.order_id is None

    def test_order_custom(self):
        order = Order(
            symbol="000001", side=OrderSide.SELL, price=50.0, volume=100,
            order_type=OrderType.MARKET, order_id="ord-1",
            status=OrderStatus.FILLED, filled_volume=100, filled_price=50.0,
        )
        assert order.order_id == "ord-1"
        assert order.order_type == OrderType.MARKET


class TestPositionModel:
    def test_position_defaults(self):
        pos = Position(symbol="600519", volume=100, avg_cost=1850.0)
        assert pos.current_price == 0.0
        assert pos.market_value == 0.0
        assert pos.pnl == 0.0


class TestMockBroker:
    @pytest.fixture
    def broker(self):
        return MockBroker(initial_cash=100000.0)

    def test_connect(self, broker):
        assert broker.connect() is True
        assert broker._connected is True

    def test_get_account_initial(self, broker):
        broker.connect()
        acct = broker.get_account()
        assert acct.cash == 100000.0
        assert acct.total_assets == 100000.0
        assert acct.positions == []

    def test_buy_order_creates_position(self, broker):
        broker.connect()
        order = broker.place_order("600519", OrderSide.BUY, 100.0, 100)
        assert order.status == OrderStatus.FILLED
        assert order.filled_volume == 100

        acct = broker.get_account()
        assert acct.cash == 90000.0

        positions = broker.get_positions()
        assert len(positions) == 1
        assert positions[0].symbol == "600519"
        assert positions[0].volume == 100
        assert positions[0].avg_cost == 100.0

    def test_sell_order_reduces_position(self, broker):
        broker.connect()
        broker.place_order("600519", OrderSide.BUY, 100.0, 200)
        broker.place_order("600519", OrderSide.SELL, 110.0, 100)

        acct = broker.get_account()
        assert acct.cash == 91000.0  # 100000 - 20000 + 11000

        positions = broker.get_positions()
        assert positions[0].volume == 100

    def test_sell_all_removes_position(self, broker):
        broker.connect()
        broker.place_order("600519", OrderSide.BUY, 100.0, 100)
        broker.place_order("600519", OrderSide.SELL, 110.0, 100)
        assert broker.get_positions() == []
        assert broker.get_account().cash == 101000.0

    def test_avg_cost_on_multiple_buys(self, broker):
        broker.connect()
        broker.place_order("600519", OrderSide.BUY, 100.0, 100)
        broker.place_order("600519", OrderSide.BUY, 200.0, 100)
        pos = broker.get_positions()[0]
        assert pos.volume == 200
        assert pos.avg_cost == 150.0

    def test_cancel_order(self, broker):
        broker.connect()
        broker.place_order("600519", OrderSide.BUY, 100.0, 100)
        order_id = broker.get_orders()[0].order_id
        assert broker.cancel_order(order_id) is True
        assert broker.get_order(order_id).status == OrderStatus.CANCELLED

    def test_cancel_nonexistent(self, broker):
        assert broker.cancel_order("nonexistent") is False

    def test_get_orders_filtered(self, broker):
        broker.connect()
        broker.place_order("600519", OrderSide.BUY, 100.0, 100)
        broker.place_order("000001", OrderSide.BUY, 50.0, 200)
        assert len(broker.get_orders(symbol="600519")) == 1
        assert len(broker.get_orders()) == 2

    def test_update_position_prices(self, broker):
        broker.connect()
        broker.place_order("600519", OrderSide.BUY, 100.0, 100)
        broker.place_order("000001", OrderSide.BUY, 50.0, 200)
        broker.update_position_prices({"600519": 110.0, "000001": 55.0})

        pos_519 = broker.get_positions()[0]
        assert pos_519.current_price == 110.0
        assert pos_519.market_value == 11000.0
        assert pos_519.pnl == 1000.0
        assert pos_519.pnl_pct == 10.0

    def test_multiple_positions(self, broker):
        broker.connect()
        broker.place_order("600519", OrderSide.BUY, 100.0, 100)
        broker.place_order("000001", OrderSide.BUY, 50.0, 200)
        assert len(broker.get_positions()) == 2
