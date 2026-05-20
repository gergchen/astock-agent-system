"""同花顺模拟交易券商适配器 — THS virtual/simulated trading broker.

Supports 同花顺虚拟账号 for paper trading validation.
Phase 1: wraps easytrader. Phase 2: native THS API.
"""

import threading
import time
from datetime import datetime
from typing import Optional

from .base import (
    Account, BrokerBase, Order, OrderSide, OrderStatus, OrderType, Position,
)


class THSBroker(BrokerBase):
    """同花顺模拟交易券商 — wraps easytrader for THS paper trading.

    Setup:
      1. 下载安装同花顺网上股票交易系统
      2. 注册模拟交易账号（同花顺模拟炒股）
      3. pip install easytrader
      4. broker = THSBroker(prepare=True)  # 首次需准备

    Usage:
      broker = THSBroker()
      broker.connect()
      broker.place_order("600519", OrderSide.BUY, 1850.0, 100)
      broker.get_positions()
    """

    def __init__(self, exe_path: Optional[str] = None, mock_fallback: bool = True):
        """
        Args:
            exe_path: 同花顺下单程序路径 (xiadan.exe)，None 则自动查找
            mock_fallback: 若 easytrader 不可用，是否降级到 MockBroker
        """
        self._exe_path = exe_path
        self._mock_fallback = mock_fallback
        self._user = None
        self._connected = False
        self._orders: dict[str, Order] = {}
        self._lock = threading.Lock()
        self._using_mock = False

    # ── 连接管理 ───────────────────────────────────────────────

    def connect(self) -> bool:
        """连接到同花顺模拟交易客户端。"""
        try:
            import easytrader
            user = easytrader.use("ths")

            if self._exe_path:
                user.prepare(self._exe_path)
            else:
                user.prepare(user.autofix_exe_path())

            self._user = user
            self._connected = True
            return True
        except ImportError:
            if self._mock_fallback:
                from .mock_broker import MockBroker
                self._mock = MockBroker()
                self._mock.connect()
                self._connected = True
                self._using_mock = True
                return True
            raise
        except Exception as e:
            if self._mock_fallback:
                from .mock_broker import MockBroker
                self._mock = MockBroker()
                self._mock.connect()
                self._connected = True
                self._using_mock = True
                return True
            raise ConnectionError(f"无法连接同花顺客户端: {e}")

    def disconnect(self) -> None:
        if self._using_mock:
            self._mock.disconnect()
        self._connected = False

    # ── 账户查询 ───────────────────────────────────────────────

    def get_account(self) -> Account:
        self._ensure_connected()
        if self._using_mock:
            return self._mock.get_account()

        balance = self._user.balance
        position_data = self._user.position
        positions = []
        total_market = 0.0
        for p in (position_data or []):
            pos = Position(
                symbol=p.get("证券代码", ""),
                volume=int(p.get("股票余额", 0)),
                avg_cost=float(p.get("成本价", 0)),
                current_price=float(p.get("市价", 0)),
                market_value=float(p.get("市值", 0)),
                pnl=float(p.get("盈亏", 0)),
                pnl_pct=float(p.get("盈亏比例(%)", 0)),
            )
            positions.append(pos)
            total_market += pos.market_value

        return Account(
            cash=float(balance.get("可用金额", 0)),
            frozen=float(balance.get("冻结金额", 0)),
            total_assets=float(balance.get("总资产", 0)),
            positions=positions,
        )

    def get_positions(self) -> list[Position]:
        acct = self.get_account()
        return acct.positions or []

    # ── 下单 ──────────────────────────────────────────────────

    def place_order(self, symbol: str, side: OrderSide, price: float,
                    volume: int, order_type: OrderType = OrderType.LIMIT) -> Order:
        self._ensure_connected()
        if self._using_mock:
            return self._mock.place_order(symbol, side, price, volume, order_type)

        with self._lock:
            if side == OrderSide.BUY:
                result = self._user.buy(symbol, price=price, amount=volume)
            else:
                result = self._user.sell(symbol, price=price, amount=volume)

        order_id = str(result.get("委托编号", datetime.now().timestamp()))
        order = Order(
            symbol=symbol,
            side=side,
            price=price,
            volume=volume,
            order_type=order_type,
            order_id=order_id,
            status=OrderStatus.PENDING,
            filled_volume=0,
            filled_price=0.0,
            created_at=datetime.now(),
        )
        self._orders[order_id] = order
        return order

    def cancel_order(self, order_id: str) -> bool:
        self._ensure_connected()
        if self._using_mock:
            return self._mock.cancel_order(order_id)

        with self._lock:
            result = self._user.cancel(order_id)
        if result.get("message") == "已受理":
            if order_id in self._orders:
                self._orders[order_id].status = OrderStatus.CANCELLED
            return True
        return False

    # ── 订单查询 ───────────────────────────────────────────────

    def get_order(self, order_id: str) -> Optional[Order]:
        self._ensure_connected()
        if self._using_mock:
            return self._mock.get_order(order_id)
        return self._orders.get(order_id)

    def get_orders(self, symbol: Optional[str] = None) -> list[Order]:
        self._ensure_connected()
        if self._using_mock:
            return self._mock.get_orders(symbol)

        # 同步实际订单状态
        try:
            entrusts = self._user.entrust
            for e in (entrusts or []):
                eid = str(e.get("委托编号", ""))
                status_text = e.get("状态", "")
                if eid in self._orders:
                    if "成交" in status_text:
                        self._orders[eid].status = OrderStatus.FILLED
                        self._orders[eid].filled_volume = int(e.get("成交数量", 0))
                        self._orders[eid].filled_price = float(e.get("成交价格", 0))
                    elif "撤" in status_text:
                        self._orders[eid].status = OrderStatus.CANCELLED
        except Exception:
            pass

        orders = list(self._orders.values())
        if symbol:
            orders = [o for o in orders if o.symbol == symbol]
        return orders

    # ── 模拟账户快捷入口 ──────────────────────────────────────

    @staticmethod
    def get_virtual_account_url() -> str:
        """获取同花顺模拟炒股注册地址。"""
        return "https://moni.10jqka.com.cn/"

    @property
    def using_mock(self) -> bool:
        """是否降级使用了 MockBroker。"""
        return self._using_mock

    def _ensure_connected(self):
        if not self._connected:
            raise RuntimeError("未连接同花顺客户端，请先调用 connect()")
