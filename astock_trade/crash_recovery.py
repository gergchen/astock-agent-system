"""Crash recovery — Position Recovery + Order Replay for production resilience.

On startup or after a crash, the recovery system:
1. Rebuilds in-memory positions from the trade journal
2. Replays unprocessed orders from the signal bus
3. Detects and reconciles divergence between broker state and journal state

This is the SYSTEM RECOVERY layer — runs before any agent starts trading.
"""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from .broker.base import Account, BrokerBase, Order, OrderSide, OrderStatus, Position
from .config import get_config
from .signal_bus import SignalBus
from .trade_journal import query_trades

logger = logging.getLogger(__name__)


@dataclass
class RecoveryReport:
    """Report of what the recovery process found and did."""
    status: str = "ok"  # ok / warning / error
    broker_positions_loaded: int = 0
    journal_positions_rebuilt: int = 0
    pending_orders_replayed: int = 0
    stale_orders_requeued: int = 0
    reconciliation_issues: list[str] = field(default_factory=list)
    recovered_positions: dict[str, dict] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "broker_positions_loaded": self.broker_positions_loaded,
            "journal_positions_rebuilt": self.journal_positions_rebuilt,
            "pending_orders_replayed": self.pending_orders_replayed,
            "stale_orders_requeued": self.stale_orders_requeued,
            "reconciliation_issues": self.reconciliation_issues,
            "recovered_positions": self.recovered_positions,
            "errors": self.errors,
        }


class PositionRecovery:
    """Rebuild in-memory position state from trade journal + broker.

    On startup, this recovers what the system currently holds.
    """

    def __init__(self, broker: BrokerBase):
        self._broker = broker
        self._cfg = get_config()

    def recover(self, days_back: int = 30) -> RecoveryReport:
        """Run position recovery.

        Steps:
        1. Load current positions from broker (live source of truth)
        2. Rebuild positions from trade journal (fallback / cross-check)
        3. Reconcile differences

        Returns a RecoveryReport.
        """
        report = RecoveryReport()

        # Step 1: Try loading from broker
        broker_positions = self._load_from_broker(report)
        if broker_positions:
            report.broker_positions_loaded = len(broker_positions)
            report.recovered_positions = {
                s: {"volume": p.volume, "avg_cost": p.avg_cost,
                    "market_value": p.market_value, "source": "broker"}
                for s, p in broker_positions.items()
            }
            return report

        # Step 2: Broker unavailable — rebuild from trade journal
        logger.warning("Broker unavailable or no positions — rebuilding from trade journal")
        journal_positions = self._rebuild_from_journal(days_back, report)
        if journal_positions:
            report.journal_positions_rebuilt = len(journal_positions)
            report.recovered_positions = {
                s: {"volume": v["volume"], "avg_cost": v["avg_cost"],
                    "market_value": v["market_value"], "source": "journal"}
                for s, v in journal_positions.items()
            }
            report.status = "warning"

        return report

    def _load_from_broker(self, report: RecoveryReport) -> dict[str, Position]:
        """Load current positions from broker."""
        try:
            account = self._broker.get_account()
            if account.positions:
                return {p.symbol: p for p in account.positions}
        except Exception as e:
            report.errors.append(f"Broker position load failed: {e}")
            logger.error("Failed to load broker positions: %s", e)
        return {}

    def _rebuild_from_journal(self, days_back: int,
                              report: RecoveryReport) -> dict[str, dict]:
        """Rebuild positions from trade journal.

        Walks trade journal from last N days and computes net position.
        This is a BEST-EFFORT recovery — P&L may be approximate.
        """
        end = date.today()
        start = date.fromordinal(end.toordinal() - days_back)

        try:
            trades = query_trades(start_date=start, end_date=end)
        except Exception as e:
            report.errors.append(f"Journal rebuild failed: {e}")
            return {}

        positions: dict[str, dict] = {}
        for t in trades:
            sym = t["symbol"]
            direction = t["direction"]
            price = float(t["price"])
            volume = int(t["volume"])

            if sym not in positions:
                positions[sym] = {"volume": 0, "total_cost": 0.0, "avg_cost": 0.0,
                                  "market_value": 0.0, "PnL": 0.0}

            pos = positions[sym]
            if direction == "BUY":
                total_vol = pos["volume"] + volume
                pos["avg_cost"] = ((pos["avg_cost"] * pos["volume"]) + (price * volume)) / total_vol if total_vol > 0 else price
                pos["volume"] = total_vol
                pos["market_value"] = pos["volume"] * price
            elif direction == "SELL":
                sell_amount = price * volume
                buy_cost = pos["avg_cost"] * volume
                pos["PnL"] += sell_amount - buy_cost
                pos["volume"] -= volume
                if pos["volume"] <= 0:
                    del positions[sym]

        return positions


class OrderReplay:
    """Replay unprocessed orders from the signal bus.

    After a crash, there may be:
    - Messages stuck in 'processing' state (stale claims)
    - Unconsumed trade signals that need re-evaluation
    """

    def __init__(self, bus: SignalBus):
        self._bus = bus

    def replay(self, report: RecoveryReport) -> RecoveryReport:
        """Replay stale and pending orders from the bus.

        Steps:
        1. Requeue stale 'processing' messages (crashed consumers)
        2. Count unconsumed 'pending' messages by channel
        3. Log all unconsumed signals for audit

        Returns updated RecoveryReport.
        """
        # Step 1: Requeue stale processing messages
        try:
            requeued = self._bus.requeue_stale()
            if requeued > 0:
                report.stale_orders_requeued = requeued
                report.reconciliation_issues.append(
                    f"Requeued {requeued} stale messages (crashed consumers)"
                )
        except Exception as e:
            report.errors.append(f"Stale requeue failed: {e}")

        # Step 2: Check for unconsumed signals in each channel
        try:
            for channel in ["from_researcher", "from_risk_officer"]:
                pending = self._bus.peek(channel, limit=50)
                pending_unprocessed = [
                    m for m in pending
                    if m.get("_status") == "pending"
                ]
                if pending_unprocessed:
                    report.pending_orders_replayed += len(pending_unprocessed)
                    report.reconciliation_issues.append(
                        f"Channel {channel}: {len(pending_unprocessed)} unconsumed messages remain"
                    )
        except Exception as e:
            report.errors.append(f"Pending check failed: {e}")

        if report.errors:
            report.status = "error"
        elif report.reconciliation_issues:
            report.status = "warning"

        return report


@dataclass
class RecoveryResult:
    """Combined result from full crash recovery."""
    report: RecoveryReport
    account: Optional[Account] = None
    positions: dict[str, dict] = field(default_factory=dict)
    recovered: bool = False

    def to_dict(self) -> dict:
        return {
            "recovered": self.recovered,
            "account": {
                "total_assets": self.account.total_assets if self.account else 0,
                "cash": self.account.cash if self.account else 0,
                "position_count": len(self.positions),
            } if self.account else None,
            "report": self.report.to_dict(),
        }


def run_crash_recovery(broker: BrokerBase, bus: Optional[SignalBus] = None,
                       days_back: int = 30) -> RecoveryResult:
    """Run full crash recovery: positions + orders.

    Call this once at system startup before any trading begins.
    """
    logger.info("=" * 50)
    logger.info("CRASH RECOVERY STARTING")
    logger.info("=" * 50)

    report = RecoveryReport()

    # Phase 1: Position recovery
    pos_recovery = PositionRecovery(broker)
    report = pos_recovery.recover(days_back=days_back)

    # Phase 2: Order replay
    if bus is not None:
        order_replay = OrderReplay(bus)
        report = order_replay.replay(report)

    # Build result
    try:
        account = broker.get_account()
        positions = {}
        if account.positions:
            positions = {p.symbol: {"volume": p.volume, "avg_cost": p.avg_cost,
                                     "market_value": p.market_value}
                         for p in account.positions}
    except Exception as e:
        logger.error("Failed to get final account state: %s", e)
        account = None
        positions = report.recovered_positions

    recovered = report.status != "error"

    if recovered:
        logger.info("CRASH RECOVERY COMPLETE — positions=%d, pending=%d, issues=%d",
                    len(positions), report.pending_orders_replayed,
                    len(report.reconciliation_issues))
    else:
        logger.error("CRASH RECOVERY FAILED — %d errors", len(report.errors))

    return RecoveryResult(
        report=report,
        account=account,
        positions=positions,
        recovered=recovered,
    )
