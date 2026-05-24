"""Slippage and commission models for realistic backtesting.

All models are deterministic — same inputs always produce same outputs.
"""

from dataclasses import dataclass
from typing import Optional


# ── Slippage Models ──


@dataclass
class SlippageResult:
    """Result of slippage calculation."""

    base_price: float
    exec_price: float
    slippage_pct: float
    slippage_reason: str


class SlippageModel:
    """Base class for slippage models."""

    def apply(self, price: float, direction: str, volume: int = 0,
              daily_vol: float = 0) -> SlippageResult:
        raise NotImplementedError


class FixedSlippage(SlippageModel):
    """Fixed percentage slippage — simplest model."""

    def __init__(self, bps: float = 1.0):
        """
        Args:
            bps: Slippage in basis points (1 bp = 0.01%). Default 1 bp.
        """
        self.bps = bps

    def apply(self, price: float, direction: str, volume: int = 0,
              daily_vol: float = 0) -> SlippageResult:
        pct = self.bps / 10000
        if direction.upper() == "BUY":
            exec_price = price * (1 + pct)
        else:
            exec_price = price * (1 - pct)
        return SlippageResult(
            base_price=price,
            exec_price=round(exec_price, 2),
            slippage_pct=round(pct * 100, 4),
            slippage_reason=f"固定滑点 {self.bps}bp",
        )


class TickSlippage(SlippageModel):
    """Tick-size based slippage for A-share market.

    A-share tick size is 0.01 CNY for most stocks.
    Adds 1 tick for small orders, scales up for larger ones.
    """

    def __init__(self, tick_size: float = 0.01, ticks: int = 1):
        self.tick_size = tick_size
        self.ticks = ticks

    def apply(self, price: float, direction: str, volume: int = 0,
              daily_vol: float = 0) -> SlippageResult:
        slip_amount = self.tick_size * self.ticks
        if direction.upper() == "BUY":
            exec_price = price + slip_amount
        else:
            exec_price = price - slip_amount
        pct = (abs(exec_price - price) / price) * 100 if price > 0 else 0
        return SlippageResult(
            base_price=price,
            exec_price=round(exec_price, 2),
            slippage_pct=round(pct, 4),
            slippage_reason=f"最小价差 {self.ticks}tick",
        )


class VolumeSlippage(SlippageModel):
    """Volume-impact slippage model.

    Slippage scales with order size relative to daily volume.
    Formula: slippage_bps = base_bps * (1 + volume_ratio * impact_factor)
    where volume_ratio = order_value / daily_turnover
    """

    def __init__(self, base_bps: float = 1.0, impact_factor: float = 10.0):
        """
        Args:
            base_bps: Minimum slippage in basis points.
            impact_factor: Multiplier for volume impact.
        """
        self.base_bps = base_bps
        self.impact_factor = impact_factor

    def apply(self, price: float, direction: str, volume: int = 0,
              daily_vol: float = 0) -> SlippageResult:
        if daily_vol > 0 and volume > 0:
            volume_ratio = (price * volume) / (daily_vol * price) if daily_vol > 0 else 0
        else:
            volume_ratio = 0

        total_bps = self.base_bps * (1 + volume_ratio * self.impact_factor)
        pct = total_bps / 10000

        if direction.upper() == "BUY":
            exec_price = price * (1 + pct)
        else:
            exec_price = price * (1 - pct)

        return SlippageResult(
            base_price=price,
            exec_price=round(exec_price, 2),
            slippage_pct=round(pct * 100, 4),
            slippage_reason=(
                f"成交量滑点 {total_bps:.1f}bp"
                if volume_ratio > 0 else f"固定滑点 {self.base_bps}bp"
            ),
        )


# ── Commission Models ──


@dataclass
class CommissionResult:
    """Result of commission calculation."""

    trade_value: float
    commission: float
    stamp_duty: float       # 印花税
    transfer_fee: float     # 过户费
    broker_fee: float       # 券商佣金
    total_cost: float
    detail: str


class CommissionModel:
    """Base class for commission models."""

    def calculate(self, price: float, volume: int, direction: str) -> CommissionResult:
        raise NotImplementedError


class FixedCommission(CommissionModel):
    """Fixed percentage commission — simple, backward-compatible."""

    def __init__(self, pct: float = 0.03):
        """
        Args:
            pct: Commission percentage (e.g. 0.03 = 0.03%).
        """
        self.pct = pct

    def calculate(self, price: float, volume: int, direction: str) -> CommissionResult:
        trade_value = price * volume
        cost = trade_value * self.pct / 100
        return CommissionResult(
            trade_value=round(trade_value, 2),
            commission=round(cost, 2),
            stamp_duty=0,
            transfer_fee=0,
            broker_fee=round(cost, 2),
            total_cost=round(cost, 2),
            detail=f"固定佣金 {self.pct}%",
        )


class AShareCommission(CommissionModel):
    """Realistic A-share commission model.

    Components:
    - 印花税 (Stamp duty): 0.05% of trade value — SELL only
    - 过户费 (Transfer fee): 0.001% of trade value — both sides
    - 券商佣金 (Broker fee): 0.025% of trade value — both sides, min 5 CNY
    """

    def __init__(self,
                 stamp_duty_pct: float = 0.05,
                 transfer_fee_pct: float = 0.001,
                 broker_fee_pct: float = 0.025,
                 broker_min_fee: float = 5.0):
        self.stamp_duty_pct = stamp_duty_pct
        self.transfer_fee_pct = transfer_fee_pct
        self.broker_fee_pct = broker_fee_pct
        self.broker_min_fee = broker_min_fee

    def calculate(self, price: float, volume: int, direction: str) -> CommissionResult:
        trade_value = price * volume
        is_sell = direction.upper() == "SELL"

        stamp_duty = (trade_value * self.stamp_duty_pct / 100) if is_sell else 0.0
        transfer_fee = trade_value * self.transfer_fee_pct / 100
        broker_fee = max(trade_value * self.broker_fee_pct / 100, self.broker_min_fee)

        total = stamp_duty + transfer_fee + broker_fee

        parts = [f"佣金{broker_fee:.2f}"]
        if stamp_duty > 0:
            parts.append(f"印花税{stamp_duty:.2f}")
        parts.append(f"过户费{transfer_fee:.2f}")

        return CommissionResult(
            trade_value=round(trade_value, 2),
            commission=round(total, 2),
            stamp_duty=round(stamp_duty, 2),
            transfer_fee=round(transfer_fee, 2),
            broker_fee=round(broker_fee, 2),
            total_cost=round(total, 2),
            detail=" + ".join(parts),
        )


# ── Preset instances ──

def get_slippage_model(name: str = "tick", **kwargs) -> SlippageModel:
    """Factory for slippage models by name."""
    models = {
        "fixed": lambda: FixedSlippage(bps=kwargs.get("bps", 1.0)),
        "tick": lambda: TickSlippage(
            tick_size=kwargs.get("tick_size", 0.01),
            ticks=kwargs.get("ticks", 1),
        ),
        "volume": lambda: VolumeSlippage(
            base_bps=kwargs.get("base_bps", 1.0),
            impact_factor=kwargs.get("impact_factor", 10.0),
        ),
    }
    factory = models.get(name)
    if factory is None:
        raise ValueError(f"Unknown slippage model: {name}. Options: {list(models)}")
    return factory()


def get_commission_model(name: str = "ashare", **kwargs) -> CommissionModel:
    """Factory for commission models by name."""
    models = {
        "fixed": lambda: FixedCommission(pct=kwargs.get("pct", 0.03)),
        "ashare": lambda: AShareCommission(
            stamp_duty_pct=kwargs.get("stamp_duty_pct", 0.05),
            transfer_fee_pct=kwargs.get("transfer_fee_pct", 0.001),
            broker_fee_pct=kwargs.get("broker_fee_pct", 0.025),
            broker_min_fee=kwargs.get("broker_min_fee", 5.0),
        ),
    }
    factory = models.get(name)
    if factory is None:
        raise ValueError(f"Unknown commission model: {name}. Options: {list(models)}")
    return factory()
